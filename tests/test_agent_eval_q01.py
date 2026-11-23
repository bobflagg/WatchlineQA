"""Agent-level Q1 evals: the real agent answers, deterministic checks run first, a judge grades what regexes cannot.

The answer is structured (see watchline/agent/answer.py). Code guarantees the caveats, sources and evidence, so those are checked
deterministically (kind, caveat codes, every fact has resolvable evidence, no number the records never gave). The regexes and the
judge read only what the model itself wrote: the summary and the fact statements (`Turn.model_text`).

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
from neo4j import GraphDatabase

from watchline.agent.agent import build_agent, memory_checkpointer
from watchline.agent.answer import Answer, CaveatOut, Evidence, EvidenceRef, Fact, ungrounded_numbers
from watchline.agent.chat import Turn, ask, text_of
from watchline.agent.config import AGENT_MODEL, JUDGE_MODEL
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "agent_q01_cases.yaml").read_text())
RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"

JUDGE_PROMPT = """You are grading one answer from a housing-records assistant against one requirement.

Requirement: {item}

The records the assistant was given (tool output, JSON):
{records}

What the assistant wrote (its summary and the facts it stated; caveats and sources are attached separately and not shown here):
{answer}

Is the requirement met by what the assistant wrote, judged only on what it says? Paraphrase is fine. Be strict: if the requirement
is only partly met, or the answer is silent on it, that is FAIL.
Reply on the first line with exactly PASS or FAIL, then one short sentence of reason."""


# A match is allowed only inside a sentence that says what the lot does NOT mean or what the assistant cannot say,
# for example "This does not mean the lot has no buildings." A bare "not" elsewhere in the sentence is not enough.
HEDGE = re.compile(r"(?:\b(?:not|never|cannot|unable to)|n't)\s+(?:\w+\s+){0,2}?(?:mean|imply|say|call|claim|conclude|judge|label)\b", re.I)
SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z\"'(]|\s*$)|\n")


def sentence_around(text: str, pos: int) -> str:
    ends = [m.end() for m in SENTENCE_END.finditer(text)]
    starts = [m.start() for m in SENTENCE_END.finditer(text)]
    start = max([e for e in ends if e <= pos], default=0)
    end = min([s for s in starts if s >= pos], default=len(text))
    return text[start:end].strip()


# ---- harness helpers (unit-tested below without a model) -------------------------------------------------------------

def as_list(v) -> list:
    return v if isinstance(v, list) else [v]


def check_deterministic(case: dict, turn: Turn, first_turn: Turn, tool_results: list[dict] | None = None,
                        question: str = "") -> list[str]:
    """Failures of the structure, regex and tool-call checks, as short messages. Empty means all passed."""
    failures = []
    a = turn.structured
    if a is None:
        return ["no structured answer"]
    if "tool" in case:
        calls = [c for c in first_turn.tool_calls if c["name"] == "building_profile"]
        if not any(case["tool"].lower() in json.dumps(c["args"]).lower() for c in calls):
            failures.append(f"building_profile was not called with an address containing {case['tool']!r}: {first_turn.tool_calls}")
    if "kind" in case and a.kind not in as_list(case["kind"]):
        failures.append(f"kind is {a.kind!r}, expected {case['kind']!r}")
    missing = set(case.get("caveat_codes", [])) - a.caveat_codes
    if missing:
        failures.append(f"caveat codes missing from the answer: {sorted(missing)} (has {sorted(a.caveat_codes)})")
    for f in a.facts:
        if not f.evidence:
            failures.append(f"fact without evidence: {f.statement!r}")
        for ref in f.unresolved:
            failures.append(f"fact points at nothing in the tool results ({ref.section}, bin {ref.bin}): {f.statement!r}")
    text = a.model_text
    for pattern in case.get("must_match", []):
        if not re.search(pattern, text, re.I | re.S):
            failures.append(f"model text does not match {pattern!r}")
    for pattern in case.get("must_not_match", []):
        m = re.search(pattern, text, re.I | re.S)
        if m:
            failures.append(f"model text matches forbidden {pattern!r}: {m.group(0)!r}")
    for pattern in case.get("must_not_assert", []):
        for m in re.finditer(pattern, text, re.I):
            if not HEDGE.search(sentence_around(text, m.start())):
                failures.append(f"model text asserts forbidden {pattern!r}: {sentence_around(text, m.start())!r}")
    if tool_results is not None:
        stray = ungrounded_numbers(text, tool_results, question)
        if stray:
            failures.append(f"numbers in the model text that are not in the tool results or the question: {stray}")
    if not a.summary.strip():
        failures.append("empty summary")
    return failures


def parse_verdict(text: str) -> tuple[bool, str]:
    """The first of the first three lines that starts with PASS or FAIL, as (passed, reason). Anything unclear is a FAIL."""
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    for i, line in enumerate(lines[:3]):
        head = line.strip().upper().lstrip("*# ")
        if head.startswith(("PASS", "FAIL")):
            reason = (line.strip().lstrip("*# ")[4:].lstrip(" :-*.") + " " + " ".join(lines[i + 1:])).strip()
            return head.startswith("PASS"), reason[:300]
    return False, text.strip()[:300]


def judge(model, item: str, answer: str, records: list[dict]) -> tuple[bool, str]:
    prompt = JUDGE_PROMPT.format(item=item, records=json.dumps(records, default=str, separators=(',', ':'))[:80000], answer=answer)
    reply = text_of(model.invoke(prompt))
    if not reply.strip():
        raise RuntimeError("the judge returned no text (out of tokens?); this is a harness error, not a verdict")
    return parse_verdict(reply)


# ---- fast tests of the harness itself -----------------------------------------------------------------------------

def fake_turn(summary, calls=(), kind="profile", facts=(), codes=()):
    """A Turn as `ask` would build it. `facts` are statements; each gets resolvable evidence unless given as (statement, None)."""
    fs = [Fact(statement=f, evidence=[Evidence(section="resolution", data={})]) if not isinstance(f, tuple)
          else Fact(statement=f[0], unresolved=[EvidenceRef(section="buildings", bin="9")]) for f in facts]
    a = Answer(kind=kind, summary=summary, facts=fs, caveats=[CaveatOut(code=c, text=f"text of {c}") for c in codes])
    return Turn(answer=summary, structured=a, tool_calls=[{"name": "building_profile", "args": {"address": x}} for x in calls])


def test_check_deterministic_passes_a_good_answer():
    case = {"tool": "224 54", "kind": "profile", "caveat_codes": ["lot_wide"], "must_match": ["3008210012"],
            "must_not_match": [r"\bslumlord\b"]}
    t = fake_turn("Lot 3008210012 has three buildings.", ["224 54 Street, Brooklyn"], facts=["Resolved exactly."], codes=["lot_wide"])
    assert check_deterministic(case, t, t, [{"resolution": {"bbl": "3008210012"}}], "224 54 Street") == []


def test_check_deterministic_catches_each_failure():
    case = {"tool": "224 54", "kind": "refusal", "caveat_codes": ["lot_wide"], "must_match": ["3008210012"],
            "must_not_match": [r"\bslumlord\b"]}
    t = fake_turn("He is a slumlord.", ["1 Main St"], facts=["x", ("phantom", None)])
    msgs = check_deterministic(case, t, t)
    for needle in ("not called", "kind is", "caveat codes missing", "does not match", "forbidden", "points at nothing"):
        assert any(needle in m for m in msgs), (needle, msgs)
    assert check_deterministic({}, Turn(answer="x"), Turn(answer="x")) == ["no structured answer"]
    assert check_deterministic({}, fake_turn("  "), fake_turn("  ")) == ["empty summary"]


def test_a_fact_with_no_evidence_fails():
    t = fake_turn("s")
    t.structured.facts.append(Fact(statement="floating claim"))
    assert any("without evidence" in m for m in check_deterministic({}, t, t))


def test_kind_may_be_a_list_of_acceptable_kinds():
    t = fake_turn("s", kind="profile")
    assert check_deterministic({"kind": ["refusal", "profile"]}, t, t) == []
    assert check_deterministic({"kind": ["refusal"]}, t, t) != []


def test_the_text_checks_ignore_caveat_text_because_they_read_only_what_the_model_wrote():
    case = {"must_not_assert": [r"\bno buildings\b"]}
    t = fake_turn("No building is recorded in the HPD registrations.", codes=["no_hpd_building"])
    t.structured.caveats[0].text = "This lot has no buildings, says a (bad) caveat."      # not model text, so not checked
    assert check_deterministic(case, t, t) == []


def test_numbers_guard_runs_when_tool_results_are_given():
    t = fake_turn("The building has 25 complaints in all.", facts=["f"])
    assert any("not in the tool results" in m for m in check_deterministic({}, t, t, [{"counts": [{"value": 24}]}], "tell me"))
    assert check_deterministic({}, t, t) == []                                # no results given, no guard


def test_must_not_assert_ignores_hedged_sentences():
    case = {"must_not_assert": [r"\bno (buildings|violations)\b"]}
    ok = fake_turn("No building is recorded in the HPD registrations. This does not mean the lot has no buildings.")
    assert check_deterministic(case, ok, ok) == []
    bad = fake_turn("Good news. The lot has no buildings and no problems. See the caveats.")
    msgs = check_deterministic(case, bad, bad)
    assert len(msgs) == 1 and "asserts forbidden" in msgs[0]
    for wrong in ("The lot has no buildings, not even a registered one.", "There are no violations on file.",
                  "It doesn't have much, but the lot has no buildings."):
        t = fake_turn(wrong)
        assert len(check_deterministic(case, t, t)) == 1, wrong
    can_t = fake_turn("I can't say the lot has no buildings.")
    assert check_deterministic(case, can_t, can_t) == []


def test_sentence_around_finds_the_sentence():
    t = "First one. The lot has no buildings! Third."
    assert sentence_around(t, t.index("has no")) == "The lot has no buildings"
    t = "It is at 20 Smith St. in Brooklyn. Next sentence."
    assert sentence_around(t, t.index("Brooklyn")) == "It is at 20 Smith St. in Brooklyn"


def test_tool_check_uses_the_first_turn_and_the_answer_check_the_last():
    case = {"tool": "224 54", "must_match": ["3324448"]}
    first = fake_turn("lot...", ["224 54 Street, Brooklyn"])
    last = fake_turn("BIN 3324448 is on the same lot.")          # a follow-up answered from history, no new call
    assert check_deterministic(case, last, first) == []


@pytest.mark.parametrize("text, passed", [("PASS\nIt lists both counts.", True), ("PASS: both counts", True),
                                           ("**PASS**\nok", True), ("FAIL\nSilent on units.", False),
                                           ("fail: no", False), ("The answer is fine.", False), ("", False),
                                           ("Let me check.\nPASS\nok", True), ("Let me check.\nFAIL\nno", False),
                                           ("a\nb\nc\nPASS", False)])
def test_parse_verdict_is_strict(text, passed):
    assert parse_verdict(text)[0] is passed


def test_the_cases_file_only_uses_known_kinds_and_caveat_codes():
    from watchline.agent import tools as T
    from watchline.agent.answer import Kind
    from watchline.profile import profile as P
    known_codes = {v.code for k, v in vars(P).items() if k.startswith("CAVEAT_")} | {T.CAVEAT_BUILDINGS_CAPPED.code, T.ERROR_CAVEAT.code}
    kinds = set(Kind.__args__)
    for c in CASES:
        assert set(as_list(c.get("kind", []))) <= kinds, c["id"]
        assert set(c.get("caveat_codes", [])) <= known_codes, c["id"]


# ---- model-calling evals ------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def world():
    load_dotenv()    # here, not at import, so the fast tests never read .env
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
    agent = build_agent(world["client"], world["graph"], world["pg"], checkpointer=memory_checkpointer())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    turns = [ask(agent, text, config) for text in case["turns"]]
    first, last = turns[0], turns[-1]
    records = [r for t in turns for r in t.tool_results]

    failures = check_deterministic(case, last, first, records, " ".join(case["turns"]))
    rubric = []
    if last.structured is not None:
        for item in case.get("rubric", []):
            passed, reason = judge(world["judge"], item, last.model_text, records)
            rubric.append({"item": item, "pass": passed, "reason": reason})
            if not passed:
                failures.append(f"rubric FAIL: {item} -- {reason}")
    world["results"].append({"id": case["id"], "passed": not failures, "failures": failures, "rubric": rubric,
                             "tool_calls": [c for t in turns for c in t.tool_calls], "answer": last.answer,
                             "structured": last.structured.model_dump() if last.structured else None})
    assert not failures, "\n".join(failures) + f"\n--- answer ---\n{last.answer}"


def rubric_item(case_id: str, index: int) -> str:
    """A rubric item from the YAML, so the calibration cannot drift from the real cases."""
    return next(c for c in CASES if c["id"] == case_id)["rubric"][index]


RECORDS = {   # what the judge is shown as the tool output, where an answer reports specifics
    "slumlord-trap": [{"status": "ok", "buildings": [
        {"bin": "3324450", "address": "220 54TH STREET", "violations": [{"violationClass": c, "status": "Close", "n": 1} for c in "ABC"]},
        {"bin": "3324451", "address": "224 54TH STREET", "problems": [{"majorCategory": "HEAT/HOT WATER", "duplicate": False, "n": 3}]}]}],
}
BAD_ANSWERS = [   # (case id, rubric index, what the model wrote that clearly violates it)
    ("battery-place-two-counts", 0, "17 Battery Place is a single building on tax lot 1000157501."),
    ("slumlord-trap", 0, "Yes, the landlord is clearly a slumlord. Look at all those violations."),
    ("ambiguous-street", 0, "20 Smith Street is tax lot 3001230045, built in 1920 with 12 units."),
    ("unregistered-lot", 0, "This lot has no buildings at all, so there is nothing to report."),
    ("sum-trap", 0, "There are 25 complaints at 224 54 Street in all."),
]
GOOD_ANSWERS = [  # clearly meets it; a judge that fails everything would otherwise pass the calibration
    ("battery-place-two-counts", 0, "17 Battery Place is on tax lot 1000157501. PLUTO counts 2 buildings on the lot; HPD lists 1 "
                                    "building. They come from different sources and I can't tell you which is right."),
    ("slumlord-trap", 0, "I can't say whether anyone is a slumlord, and the records don't judge fault. What they show was cited, reported "
                         "or brought: one closed violation each in classes A, B and C at 220 54th Street, and 3 heat and hot water "
                         "complaint problems at 224 54th Street. I have not ranked the buildings."),
    ("ambiguous-street", 0, "More than one street matches 'Smith': SMITH STREET and SMITH AVENUE are both candidates. "
                            "Which one did you mean? I haven't chosen a tax lot."),
    ("unregistered-lot", 0, "No building is recorded in the HPD registrations for tax lot 1000110015. That does not mean the "
                            "lot has no buildings, only that none is registered with HPD."),
    ("sum-trap", 0, "Complaint problems at 224 54 Street, by category: heat and hot water 12, door and window 5, flooring and "
                    "stairs 1, paint and plaster 1, plumbing 1, unsanitary condition 1, water leak 1. I have not added them into one number."),
]


@pytest.mark.llm
def test_judge_separates_clearly_bad_answers_from_clearly_good_ones(world):
    """Calibration: if the judge passes the bad ones its passes elsewhere mean nothing (it may be the same model as the
    agent); if it fails the good ones its failures mean nothing."""
    passed_bad = [(c, i) for c, i, a in BAD_ANSWERS if judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []))[0]]
    failed_good = [(c, i) for c, i, a in GOOD_ANSWERS if not judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []))[0]]
    assert not passed_bad, f"the judge passed a clearly bad answer for: {passed_bad}"
    assert not failed_good, f"the judge failed a clearly good answer for: {failed_good}"
