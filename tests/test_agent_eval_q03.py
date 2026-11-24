"""Agent-level Q3 evals: the real agent answers questions about the deed grantee and the HPD registered owner.

The judge (rubric grading and its calibration) runs only with EVAL_JUDGE=1; otherwise only the deterministic checks run.
Same method as test_agent_eval_q01.py and test_agent_eval_q02.py (deterministic checks on the structured answer first, a judge only for
what regexes cannot decide, and the judge calibrated against clearly good and clearly bad answers), and the same helpers. Cases are in
tests/evals/agent_q03_cases.yaml. `make eval-agent` runs them; they need EVAL_ANTHROPIC_API_KEY, Neo4j and the sidecar, cost money, and vary.
"""
import json
import os
import time
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase
from test_agent_eval_q01 import USE_JUDGE, as_list, check_deterministic, fake_turn, judge, run_case

from watchline.agent.agent import build_agent, memory_checkpointer
from watchline.agent.config import (
    AGENT_MODEL,
    EVAL_KEY_ENV,
    JUDGE_MODEL,
    MissingKey,
    eval_agent_model,
    eval_judge_model,
)
from watchline.deeds.deeds import Neo4jDeedGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "agent_q03_cases.yaml").read_text())
RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"
TOOLS = ("building_profile", "registered_owner", "deed_vs_owner")


# ---- fast tests: the cases file and the patterns ------------------------------------------------------------------------

def test_the_cases_file_only_uses_known_kinds_tools_and_caveat_codes():
    from watchline.agent import tools as T
    from watchline.agent.answer import Kind
    from watchline.deeds import deeds as D
    from watchline.profile import profile as P
    from watchline.registration import registration as R
    known = ({v.code for m in (P, R, D) for k, v in vars(m).items() if k.startswith("CAVEAT_")}
             | {T.CAVEAT_BUILDINGS_CAPPED.code, T.CAVEAT_DEEDS_CAPPED.code, T.CAVEAT_COMPARISON_CAPPED.code, T.ERROR_CAVEAT.code})
    for c in CASES:
        assert set(as_list(c.get("kind", []))) <= set(Kind.__args__), c["id"]
        assert set(c.get("caveat_codes", [])) <= known, c["id"]
        assert c.get("tool_name", "deed_vs_owner") in TOOLS and c.get("last_tool", "deed_vs_owner") in TOOLS, c["id"]
        assert c["turns"] and (c.get("rubric") or c.get("must_match")), c["id"]


def test_case_ids_are_unique():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))


def test_the_same_party_pattern_catches_the_claim_and_allows_the_hedge():
    pats = next(c for c in CASES if c["id"] == "a-exact-match-is-not-same-party")["must_not_assert"]
    bad = fake_turn("The grantee is the same party as the registered owner, so 5413 PLAZA LLC is the same owner.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, bad, bad))
    claim = fake_turn("The deed grantee is the same party as the owner of record.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, claim, claim))
    hedged = fake_turn("The names match as recorded; that does not show they are the same party.")
    assert check_deterministic({"must_not_assert": pats}, hedged, hedged) == []
    direct = fake_turn("5413 PLAZA LLC is the same company as the registrant.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, direct, direct))


def test_the_sale_patterns_catch_a_sale_claim_and_allow_the_denial():
    pats = next(c for c in CASES if c["id"] == "zero-amount-is-not-a-sale")["must_not_assert"]
    bad = fake_turn("The property was sold for 0 dollars, a free sale.")
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, bad, bad))
    ok = fake_turn("The deed records an amount of 0. That does not mean it was sold for free.")
    assert check_deterministic({"must_not_assert": pats}, ok, ok) == []


# ---- model-calling evals ------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def world(eval_guard):
    load_dotenv()    # here, not at import, so the fast tests never read .env
    try:
        agent_llm, judge_llm = eval_agent_model(), eval_judge_model().with_config(callbacks=[eval_guard])
    except MissingKey:
        pytest.fail(f"{EVAL_KEY_ENV} is not set: the eval runner will not start without its own key (see .env.example).")
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
    db = os.environ["NEO4J_DATABASE"]
    results: list[dict] = []
    yield dict(client=client, graph=Neo4jGraph(driver, db), pg=Neo4jProfileGraph(driver, db), rg=Neo4jDeedGraph(driver, db),
               judge=judge_llm, model=agent_llm, guard=eval_guard, results=results)
    driver.close()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"q03-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"agent_model": AGENT_MODEL, "judge_model": JUDGE_MODEL, "cases": results}, indent=1))


@pytest.mark.llm
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_agent_eval_q03(world, case):
    turns, usage = run_case(world, case, lambda: build_agent(world["client"], world["graph"], world["pg"], world["rg"],
                                                             model=world["model"], checkpointer=memory_checkpointer()))
    first, last = turns[0], turns[-1]
    records = [r for t in turns for r in t.tool_results]

    failures = check_deterministic(case, last, first, records, " ".join(case["turns"]))
    rubric = []
    if last.structured is not None and USE_JUDGE:
        for item in case.get("rubric", []):
            passed, reason = judge(world["judge"], item, last.model_text, records, world["guard"])
            rubric.append({"item": item, "pass": passed, "reason": reason})
            if not passed:
                failures.append(f"rubric FAIL: {item} -- {reason}")
    world["results"].append({"id": case["id"], "passed": not failures, "failures": failures, "rubric": rubric,
                             "tool_calls": [c for t in turns for c in t.tool_calls], "answer": last.answer, "corrected": last.corrected, "usage": usage,
                             "structured": last.structured.model_dump() if last.structured else None})
    assert not failures, "\n".join(failures) + f"\n--- answer ---\n{last.answer}"


def rubric_item(case_id: str, index: int) -> str:
    """A rubric item from the YAML, so the calibration cannot drift from the real cases."""
    return next(c for c in CASES if c["id"] == case_id)["rubric"][index]


_SRC = ["ACRIS deeds and parties (data through 2026-05-31)", "HPD registrations (data through 2026-05-29)"]


def _pair(grantee, owner, name, addr):
    return {"documentId": "2025032100031001", "grantee": grantee, "owner": owner, "ownerType": "CorporateOwner",
            "nameAgreement": {"outcome": name, "rule": "N1" if name == "exact_normalized" else None},
            "addressAgreement": {"outcome": addr, "rule": "A1"}}


PLAZA = [{"status": "ok", "resolution": {"bbl": "3008260002"}, "deeds": [{
    "documentId": "2025032100031001", "docType": "DEED", "docDate": "2025-03-14", "recordedDate": "2025-04-02", "amount": 0, "otherLots": 0,
    "grantees": [{"name": "5413 PLAZA LLC", "mailingAddress": "746 61ST STREET", "addressLine2": None, "zip": "11220"}]}],
    "owners": [{"contactType": "CorporateOwner", "name": "5413 PLAZA LLC", "mailingAddress": "746 61ST STREET", "zip": "11220"}],
    "comparison": [_pair("5413 PLAZA LLC", "5413 PLAZA LLC", "exact_normalized", "same")], "sources": _SRC}]
TURNPIKE = [{"status": "ok", "resolution": {"bbl": "3008080025"}, "deeds": [{
    "documentId": "2018092900072001", "docType": "DEED", "docDate": "2018-09-26", "recordedDate": "2018-10-18", "amount": 4000000, "otherLots": 0,
    "grantees": [{"name": "AADVA REALTY LLC"}, {"name": "K S TURNPIKE LLC"}]}],
    "owners": [{"contactType": "CorporateOwner", "name": "KS Turnpike LLC"}],
    "comparison": [_pair("AADVA REALTY LLC", "KS Turnpike LLC", "different", "differs"),
                   _pair("K S TURNPIKE LLC", "KS Turnpike LLC", "different", "differs")], "sources": _SRC}]
NO_DEED = [{"status": "ok", "resolution": {"bbl": "1000117501"}, "deeds": [], "owners": [{"contactType": "CorporateOwner", "name": "15 STONE LLC"}],
            "comparison": [], "caveats": [{"code": "no_deed_found", "text": "No deed is recorded for this lot in the data."}]}]
RECORDS = {"a-exact-match-is-not-same-party": PLAZA, "zero-amount-is-not-a-sale": PLAZA, "g-spelling-difference-not-resolved": TURNPIKE,
           "no-deed-is-not-never-sold": NO_DEED}
BAD_ANSWERS = [   # (case id, rubric index, what the model wrote that clearly violates it)
    ("a-exact-match-is-not-same-party", 0, "5413 PLAZA LLC received the deed and is the same company as the registered owner, so it owns the building."),
    ("zero-amount-is-not-a-sale", 0, "Yes, the property was sold in the most recent deed, for nothing: a free sale."),
    ("g-spelling-difference-not-resolved", 1, "K S TURNPIKE LLC and KS Turnpike LLC are the same company, just spelled differently, so the grantee is the owner."),
    ("no-deed-is-not-never-sold", 0, "There is no deed, so the building has never changed hands. The grantee is 15 STONE LLC."),
]
GOOD_ANSWERS = [  # clearly meets it; a judge that fails everything would otherwise pass the calibration
    ("a-exact-match-is-not-same-party", 0, "The grantee on the most recent deed is 5413 PLAZA LLC, and the HPD registered owner is also recorded as "
                                           "5413 PLAZA LLC. The recorded names match exactly after normalizing case and spacing; that compares "
                                           "recorded names and does not show they are the same party or that anyone owns the building."),
    ("zero-amount-is-not-a-sale", 0, "The most recent deed, recorded 2025-04-02, records an amount of 0. A deed records a transfer of title, "
                                     "not a sale, and 0 is not a price, so I can't say it was sold."),
    ("g-spelling-difference-not-resolved", 1, "The registered owner is recorded as KS Turnpike LLC and one grantee as K S TURNPIKE LLC. The records "
                                              "show these as different names, and I am not deciding whether they refer to the same company."),
    ("no-deed-is-not-never-sold", 0, "No deed is recorded for this lot in the data, which does not mean it never changed hands. I can't name a "
                                     "grantee. 15 STONE LLC appears only as the HPD registered owner."),
]


@pytest.mark.llm
@pytest.mark.skipif(not USE_JUDGE, reason="the judge is off; set EVAL_JUDGE=1 to run rubric grading and its calibration")
def test_judge_separates_clearly_bad_answers_from_clearly_good_ones(world):
    """Calibration: if the judge passes the bad ones its passes elsewhere mean nothing (it may be the same model as the
    agent); if it fails the good ones its failures mean nothing."""
    passed_bad = [(c, i) for c, i, a in BAD_ANSWERS if judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []), world["guard"])[0]]
    failed_good = [(c, i) for c, i, a in GOOD_ANSWERS if not judge(world["judge"], rubric_item(c, i), a, RECORDS.get(c, []), world["guard"])[0]]
    assert not passed_bad, f"the judge passed a clearly bad answer for: {passed_bad}"
    assert not failed_good, f"the judge failed a clearly good answer for: {failed_good}"
