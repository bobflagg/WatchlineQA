"""Agent-level Q2 evals: the real agent answers questions about HPD registered owners and registration dates.

Same method as test_agent_eval_q01.py (deterministic checks on the structured answer first, a judge only for what regexes cannot
decide, and the judge calibrated against clearly good and clearly bad answers), and the same helpers. Cases are in
tests/evals/agent_q02_cases.yaml. `make eval-agent` runs them; they need ANTHROPIC_API_KEY, Neo4j and the sidecar, cost money, and vary.
"""
import json
import os
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase
from test_agent_eval_q01 import USE_JUDGE, as_list, check_deterministic, fake_turn, judge

from watchline.agent.agent import build_agent, memory_checkpointer
from watchline.agent.chat import ask
from watchline.agent.config import AGENT_MODEL, JUDGE_MODEL
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph
from watchline.registration.registration import Neo4jRegistrationGraph

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "agent_q02_cases.yaml").read_text())
RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"


# ---- fast tests: the cases file and the harness additions --------------------------------------------------------------

def test_the_cases_file_only_uses_known_kinds_tools_and_caveat_codes():
    from watchline.agent import tools as T
    from watchline.agent.answer import Kind
    from watchline.profile import profile as P
    from watchline.registration import registration as R
    known = {v.code for m in (P, R) for k, v in vars(m).items() if k.startswith("CAVEAT_")} | {T.CAVEAT_BUILDINGS_CAPPED.code, T.ERROR_CAVEAT.code}
    for c in CASES:
        assert set(as_list(c.get("kind", []))) <= set(Kind.__args__), c["id"]
        assert set(c.get("caveat_codes", [])) <= known, c["id"]
        assert c.get("tool_name", "building_profile") in ("building_profile", "registered_owner"), c["id"]
        assert c.get("last_tool", "registered_owner") in ("building_profile", "registered_owner"), c["id"]
        assert c["turns"] and (c.get("rubric") or c.get("must_match")), c["id"]


def test_case_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


def test_tool_name_decides_which_tool_call_counts():
    case = {"tool": "5413 7", "tool_name": "registered_owner"}
    wrong = fake_turn("s", ["5413 7 Avenue, Brooklyn"])                        # a building_profile call
    assert any("registered_owner was not called" in m for m in check_deterministic(case, wrong, wrong))
    right = fake_turn("s")
    right.tool_calls = [{"name": "registered_owner", "args": {"address": "5413 7 Avenue, Brooklyn"}}]
    assert check_deterministic(case, right, right) == []


def test_last_tool_is_checked_on_the_final_turn_only():
    case = {"tool": "224 54", "last_tool": "registered_owner"}
    first = fake_turn("lot", ["224 54 Street, Brooklyn"])
    last = fake_turn("owner")                                                  # a follow-up that made no call
    assert any("registered_owner was not called in the final turn" in m for m in check_deterministic(case, last, first))
    last.tool_calls = [{"name": "registered_owner", "args": {"address": "224 54 Street, Brooklyn"}}]
    assert check_deterministic(case, last, first) == []


def test_the_title_and_current_patterns_catch_what_they_should_and_allow_hedges():
    case = next(c for c in CASES if c["id"] == "who-owns-is-not-title")
    bad = fake_turn("The building is owned by 438 52 ST OWNERS CORP.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": case["must_not_assert"]}, bad, bad))
    ok = fake_turn("438 52 ST OWNERS CORP is the registered owner. This does not say who owns the building outright.")
    assert check_deterministic({"must_not_assert": case["must_not_assert"]}, ok, ok) == []
    ended = next(c for c in CASES if c["id"] == "ended-registration-not-current")
    cur = fake_turn("The current registered owner is an individual.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": ended["must_not_assert"]}, cur, cur))


def test_spelling_patterns_need_both_spellings():
    import re
    pats = next(c for c in CASES if c["id"] == "owner-name-spellings-kept")["must_match"][-2:]
    both = "HP SUNSET PARK I HDFC INC. (two buildings) and HP SUNSET PARK I HDFC INC (BIN 3324451)."
    assert all(re.search(p, both) for p in pats)
    only_with_period = "HP SUNSET PARK I HDFC INC. for all three."
    assert not all(re.search(p, only_with_period) for p in pats)


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
    yield dict(client=client, graph=Neo4jGraph(driver, db), pg=Neo4jProfileGraph(driver, db), rg=Neo4jRegistrationGraph(driver, db),
               judge=ChatAnthropic(model=JUDGE_MODEL, max_tokens=2000), results=results)
    driver.close()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"q02-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"agent_model": AGENT_MODEL, "judge_model": JUDGE_MODEL, "cases": results}, indent=1))


@pytest.mark.llm
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_agent_eval_q02(world, case):
    agent = build_agent(world["client"], world["graph"], world["pg"], world["rg"], checkpointer=memory_checkpointer())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    turns = [ask(agent, text, config) for text in case["turns"]]
    first, last = turns[0], turns[-1]
    records = [r for t in turns for r in t.tool_results]

    failures = check_deterministic(case, last, first, records, " ".join(case["turns"]))
    rubric = []
    if last.structured is not None and USE_JUDGE:
        for item in case.get("rubric", []):
            passed, reason = judge(world["judge"], item, last.model_text, records)
            rubric.append({"item": item, "pass": passed, "reason": reason})
            if not passed:
                failures.append(f"rubric FAIL: {item} -- {reason}")
    world["results"].append({"id": case["id"], "passed": not failures, "failures": failures, "rubric": rubric,
                             "tool_calls": [c for t in turns for c in t.tool_calls], "answer": last.answer, "corrected": last.corrected,
                             "structured": last.structured.model_dump() if last.structured else None})
    assert not failures, "\n".join(failures) + f"\n--- answer ---\n{last.answer}"


def rubric_item(case_id: str, index: int) -> str:
    """A rubric item from the YAML, so the calibration cannot drift from the real cases."""
    return next(c for c in CASES if c["id"] == case_id)["rubric"][index]


ENDED = [{"status": "ok", "resolution": {"bbl": "3008210019"}, "registration_buildings": [{"bin": "3014490", "addressed": True, "registrations": [
    {"registrationId": 306882, "lastRegistered": "2020-08-31", "registrationEnd": "2021-09-01",
     "owners": [{"contactType": "IndividualOwner", "name": "A PERSON"}]}]}], "sources": ["HPD registrations (data through 2026-05-29)"]}]
NO_BUILDING = [{"status": "ok", "resolution": {"bbl": "1000110015"}, "registration_buildings": [],
                "caveats": [{"code": "no_hpd_building", "text": "No building is recorded in the HPD registrations for this lot."}]}]
PLAZA = [{"status": "ok", "resolution": {"bbl": "3008260002"}, "registration_buildings": [{"bin": "3014788", "addressed": True, "registrations": [
    {"registrationId": 316103, "lastRegistered": "2025-09-30", "registrationEnd": "2026-09-01",
     "owners": [{"contactType": "CorporateOwner", "name": "5413 PLAZA LLC"}]}]}]}]
RECORDS = {"ended-registration-not-current": ENDED, "no-hpd-building-no-owner-inferred": NO_BUILDING, "a-registered-owner": PLAZA,
           "managing-agent-trap": PLAZA}
BAD_ANSWERS = [   # (case id, rubric index, what the model wrote that clearly violates it)
    ("a-registered-owner", 0, "5413 PLAZA LLC owns 5413 7 Avenue and holds title to the building."),
    ("ended-registration-not-current", 0, "The current registered owner is an individual, A PERSON, registered on 2020-08-31."),
    ("no-hpd-building-no-owner-inferred", 0, "The registered owner is probably the building's landlord. The lot has no owner on file, so it is unowned."),
    ("managing-agent-trap", 0, "The managing agent is 5413 PLAZA LLC, the registered owner."),
]
GOOD_ANSWERS = [  # clearly meets it; a judge that fails everything would otherwise pass the calibration
    ("a-registered-owner", 0, "HPD's registration lists 5413 PLAZA LLC as the registered owner (a corporate owner). That records who "
                              "registered the building, not who holds title."),
    ("ended-registration-not-current", 0, "The HPD registration (306882) lists an individual owner, but it ended on 2021-09-01, before the "
                                          "data's snapshot date of 2026-05-29, so it does not show a current registered owner."),
    ("no-hpd-building-no-owner-inferred", 0, "No building is recorded in the HPD registrations for tax lot 1000110015, so there is no "
                                             "registration or registered owner to read. I am not inferring an owner."),
    ("managing-agent-trap", 0, "I can't tell you the managing agent: the records I can read here list registered owners, not managing agents. "
                               "I am not treating the registered owner as the agent."),
]


@pytest.mark.llm
@pytest.mark.skipif(not USE_JUDGE, reason="the judge is off; set EVAL_JUDGE=1 to run rubric grading and its calibration")
def test_judge_separates_clearly_bad_answers_from_clearly_good_ones(world):
    """Calibration: if the judge passes the bad ones its passes elsewhere mean nothing (it may be the same model as the
    agent); if it fails the good ones its failures mean nothing."""
    passed_bad = [(c, i) for c, i, a in BAD_ANSWERS if judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []))[0]]
    failed_good = [(c, i) for c, i, a in GOOD_ANSWERS if not judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []))[0]]
    assert not passed_bad, f"the judge passed a clearly bad answer for: {passed_bad}"
    assert not failed_good, f"the judge failed a clearly good answer for: {failed_good}"
