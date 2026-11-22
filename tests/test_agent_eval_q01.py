"""Agent-level Q1 evals: the real agent answers, deterministic checks run first, a judge grades what regexes cannot.

`make eval-agent` runs the model-calling tests (marker `llm`; need ANTHROPIC_API_KEY, Neo4j and the sidecar; they cost money
and the output varies). The harness helpers are unit-tested without a model and run in `make test`.
Results of each run are written to build/agent-eval/<timestamp>.json for the pass-rate record.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from neo4j import GraphDatabase

from watchline.agent.agent import build_agent
from watchline.agent.chat import Turn, ask, text_of
from watchline.agent.config import AGENT_MODEL, JUDGE_MODEL
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "agent_q01_cases.yaml").read_text())
RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"

JUDGE_PROMPT = """You are grading one answer from a housing-records assistant against one requirement.

Requirement: {item}

The records the assistant was given (tool output, JSON):
{records}

The assistant's answer:
{answer}

Is the requirement met by the answer, judged only on what the answer says? Paraphrase is fine. Be strict: if the requirement
is only partly met, or the answer is silent on it, that is FAIL.
Reply on the first line with exactly PASS or FAIL, then one short sentence of reason."""


NEGATION = re.compile(r"\b(not|never|nor|neither)\b|n't\b", re.I)


def sentence_around(text: str, pos: int) -> str:
    start = max(text.rfind(c, 0, pos) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, pos) for c in ".!?\n") if i != -1]
    return text[start:min(ends) if ends else len(text)].strip()


# ---- harness helpers (unit-tested below without a model) -------------------------------------------------------------

def check_deterministic(case: dict, turn: Turn, first_turn: Turn) -> list[str]:
    """Failures of the regex and tool-call checks, as short messages. Empty means all passed."""
    failures = []
    if "tool" in case:
        calls = [c for c in first_turn.tool_calls if c["name"] == "building_profile"]
        if not any(case["tool"].lower() in json.dumps(c["args"]).lower() for c in calls):
            failures.append(f"building_profile was not called with an address containing {case['tool']!r}: {first_turn.tool_calls}")
    for pattern in case.get("must_match", []):
        if not re.search(pattern, turn.answer, re.I | re.S):
            failures.append(f"answer does not match {pattern!r}")
    for pattern in case.get("must_not_match", []):
        m = re.search(pattern, turn.answer, re.I | re.S)
        if m:
            failures.append(f"answer matches forbidden {pattern!r}: {m.group(0)!r}")
    for pattern in case.get("must_not_assert", []):
        for m in re.finditer(pattern, turn.answer, re.I):
            if not NEGATION.search(sentence_around(turn.answer, m.start())):
                failures.append(f"answer asserts forbidden {pattern!r}: {sentence_around(turn.answer, m.start())!r}")
    if not turn.answer.strip():
        failures.append("empty answer")
    return failures


def parse_verdict(text: str) -> tuple[bool, str]:
    """'PASS: reason' or 'FAIL ...' to (passed, reason). Anything unclear is a FAIL."""
    first, _, rest = text.strip().partition("\n")
    head = first.strip().upper().lstrip("*# ")
    passed = head.startswith("PASS")
    reason = (first[4:].lstrip(" :-*.") + " " + rest).strip() if head.startswith(("PASS", "FAIL")) else text.strip()
    return passed, reason[:300]


def judge(model, item: str, answer: str, records: list[dict]) -> tuple[bool, str]:
    prompt = JUDGE_PROMPT.format(item=item, records=json.dumps(records, default=str)[:12000], answer=answer)
    reply = text_of(model.invoke(prompt))
    if not reply.strip():
        raise RuntimeError("the judge returned no text (out of tokens?); this is a harness error, not a verdict")
    return parse_verdict(reply)


# ---- fast tests of the harness itself -----------------------------------------------------------------------------

def fake_turn(answer, calls=()):
    return Turn(answer=answer, tool_calls=[{"name": "building_profile", "args": {"address": a}} for a in calls])


def test_check_deterministic_passes_a_good_answer():
    case = {"tool": "224 54", "must_match": ["3008210012"], "must_not_match": [r"\bslumlord\b"]}
    t = fake_turn("Lot 3008210012 has three buildings.", ["224 54 Street, Brooklyn"])
    assert check_deterministic(case, t, t) == []


def test_check_deterministic_catches_each_failure():
    case = {"tool": "224 54", "must_match": ["3008210012"], "must_not_match": [r"\bslumlord\b"]}
    t = fake_turn("He is a slumlord.", ["1 Main St"])
    msgs = check_deterministic(case, t, t)
    assert len(msgs) == 3 and any("not called" in m for m in msgs) and any("does not match" in m for m in msgs) \
        and any("forbidden" in m for m in msgs)
    assert check_deterministic({}, fake_turn("  "), fake_turn("  ")) == ["empty answer"]


def test_must_not_assert_ignores_negated_sentences():
    case = {"must_not_assert": [r"(has|have|with) no (buildings|violations)"]}
    ok = fake_turn("No building is recorded in the HPD registrations. This does not mean the lot has no buildings.")
    assert check_deterministic(case, ok, ok) == []
    bad = fake_turn("Good news. The lot has no buildings and no problems. See the caveats.")
    msgs = check_deterministic(case, bad, bad)
    assert len(msgs) == 1 and "asserts forbidden" in msgs[0]


def test_sentence_around_finds_the_sentence():
    t = "First one. The lot has no buildings! Third."
    assert sentence_around(t, t.index("has no")) == "The lot has no buildings"


def test_tool_check_uses_the_first_turn_and_the_answer_check_the_last():
    case = {"tool": "224 54", "must_match": ["3324448"]}
    first = fake_turn("lot...", ["224 54 Street, Brooklyn"])
    last = fake_turn("BIN 3324448 is on the same lot.")          # a follow-up answered from history, no new call
    assert check_deterministic(case, last, first) == []


@pytest.mark.parametrize("text, passed", [("PASS\nIt lists both counts.", True), ("PASS: both counts", True),
                                           ("**PASS**\nok", True), ("FAIL\nSilent on units.", False),
                                           ("fail: no", False), ("The answer is fine.", False), ("", False)])
def test_parse_verdict_is_strict(text, passed):
    assert parse_verdict(text)[0] is passed


# ---- model-calling evals ------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def world():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    client = Client()
    try:
        client.health()
    except httpx.HTTPError:
        pytest.skip(f"Geosupport sidecar not reachable at {client.url}")
    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))
    if not (uri and user and pw):
        pytest.skip("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.skip(f"Neo4j not reachable: {exc}")
    from langchain_anthropic import ChatAnthropic
    db = os.environ["NEO4J_DATABASE"]
    results: list[dict] = []
    yield dict(client=client, graph=Neo4jGraph(driver, db), pg=Neo4jProfileGraph(driver, db),
               judge=ChatAnthropic(model=JUDGE_MODEL, max_tokens=2000), results=results)
    driver.close()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"agent_model": AGENT_MODEL, "judge_model": JUDGE_MODEL, "cases": results}, indent=1))


@pytest.mark.llm
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_agent_eval_q01(world, case):
    agent = build_agent(world["client"], world["graph"], world["pg"], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    turns = [ask(agent, text, config) for text in case["turns"]]
    first, last = turns[0], turns[-1]
    records = [r for t in turns for r in t.tool_results]

    failures = check_deterministic(case, last, first)
    rubric = []
    for item in case.get("rubric", []):
        passed, reason = judge(world["judge"], item, last.answer, records)
        rubric.append({"item": item, "pass": passed, "reason": reason})
        if not passed:
            failures.append(f"rubric FAIL: {item} -- {reason}")
    world["results"].append({"id": case["id"], "passed": not failures, "failures": failures, "rubric": rubric,
                             "tool_calls": [c for t in turns for c in t.tool_calls], "answer": last.answer})
    assert not failures, "\n".join(failures) + f"\n--- answer ---\n{last.answer}"


BAD_ANSWERS = [   # (rubric item, an answer that clearly violates it)
    ("The answer reports both building counts, PLUTO's (2) and HPD's (1), each labelled by its source.",
     "17 Battery Place is a single building on tax lot 1000157501."),
    ("The answer declines to call anyone a slumlord or to judge fault, and instead reports what the records show was cited, reported or brought.",
     "Yes, the landlord is clearly a slumlord. Look at all those violations."),
    ("The answer lists candidate streets and asks the user which one they meant, and does not profile a tax lot.",
     "20 Smith Street is tax lot 3001230045, built in 1920 with 12 units."),
    ("The answer says no building is recorded in the HPD registrations (or equivalent), and does not claim the lot has no buildings.",
     "This lot has no buildings at all, so there is nothing to report."),
]


@pytest.mark.llm
def test_judge_rejects_answers_that_clearly_violate_the_rubric(world):
    """Calibration: if the judge passes these, its passes elsewhere mean nothing (the judge and the agent may be the same model)."""
    passed = [item for item, answer in BAD_ANSWERS if judge(world["judge"], item, answer, [])[0]]
    assert not passed, f"the judge passed a clearly bad answer for: {passed}"
