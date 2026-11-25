"""Agent-level evals for the tools of slices A, B and D: building_contacts, deed_timeline, open_violations, litigation_cases.

Same method as test_agent_eval_q03.py (deterministic checks on the structured answer first, a judge only with EVAL_JUDGE=1 for what regexes
cannot decide, and the same helpers). Cases are in tests/evals/agent_slices_cases.yaml. `make eval-agent` runs them; they need
EVAL_ANTHROPIC_API_KEY, Neo4j and the sidecar, cost money and vary run to run. The fast tests at the top run in `make test` with no model.
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
from watchline.deeds.timeline import Neo4jTimelineGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "agent_slices_cases.yaml").read_text())
RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"
TOOLS = ("building_contacts", "deed_timeline", "open_violations", "litigation_cases")


def case(case_id: str) -> dict:
    return next(c for c in CASES if c["id"] == case_id)


# ---- fast tests: the cases file, the patterns, and the wiring ------------------------------------------------------------

def test_the_cases_file_only_uses_known_kinds_tools_and_caveat_codes():
    from watchline.agent import tools as T
    from watchline.agent.answer import Kind
    from watchline.conditions import conditions as K
    from watchline.contacts import contacts as CT
    from watchline.deeds import deeds as D
    from watchline.deeds import timeline as TL
    from watchline.profile import profile as P
    from watchline.registration import registration as R
    known = ({v.code for m in (P, R, D, TL, CT, K) for k, v in vars(m).items() if k.startswith("CAVEAT_")}
             | {v.code for k, v in vars(T).items() if k.startswith("CAVEAT_") and hasattr(v, "code")})
    for c in CASES:
        assert set(as_list(c["kind"])) <= set(Kind.__args__), c["id"]
        assert set(c.get("caveat_codes", [])) <= known, (c["id"], set(c.get("caveat_codes", [])) - known)
        assert c["tool_name"] in TOOLS, c["id"]
        assert c["turns"] and c.get("rubric") and c.get("must_match"), c["id"]


def test_case_ids_are_unique_and_every_tool_has_a_case():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) and {c["tool_name"] for c in CASES} == set(TOOLS)


def test_all_four_tools_are_registered_when_the_graph_can_serve_them(monkeypatch):
    from test_agent_tools import FakeClient, FakeGraph, resolved
    from test_profile import BUILDINGS, FakePG

    import watchline.agent.agent as A
    seen = {}
    monkeypatch.setattr(A, "create_deep_agent", lambda **kw: seen.update(names=sorted(t.name for t in kw["tools"])) or object())

    class Everything(Neo4jTimelineGraph):
        def __init__(self):               # no database: only the methods are looked at, to decide which tools exist
            pass

    build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), Everything(), model="claude-haiku-5-5", checkpointer=None)
    assert seen["names"] == sorted(["building_profile", "registered_owner", "deed_vs_owner", *TOOLS])


def test_the_agent_learns_when_to_use_each_new_tool_from_its_prompt_and_description():
    from watchline.agent.agent import system_prompt
    prompt = system_prompt()
    for name in TOOLS:
        assert f"`{name}`" in prompt, name
    assert "never add classes into one number" in prompt and "never \"the owner\"" in prompt


def test_the_owner_patterns_catch_the_claim_and_allow_the_denial():
    pats = case("agent-is-not-the-owner")["must_not_assert"]
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, fake_turn("JAY WONG is the owner of the building."), fake_turn("x")))
    assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, fake_turn("The agent is the registered owner."), fake_turn("x")))
    ok = fake_turn("JAY WONG is recorded as the Agent. That does not mean JAY WONG is the owner; the owner is recorded as 5413 PLAZA LLC.")
    assert check_deterministic({"must_not_assert": pats}, ok, ok) == []


def test_the_sale_patterns_catch_the_claim_and_allow_the_denial():
    pats = case("zero-amount-deeds-are-not-sales")["must_not_assert"]
    for bad in ("Seven of them were sales.", "The 1978 deed was a free sale.", "It was sold for nothing."):
        assert any("asserts forbidden" in m for m in check_deterministic({"must_not_assert": pats}, fake_turn(bad), fake_turn(bad))), bad
    ok = fake_turn("Seven deeds record an amount of 0, which does not mean they were free sales.")
    assert check_deterministic({"must_not_assert": pats}, ok, ok) == []


def test_the_harassment_patterns_catch_a_finding_about_the_owner_and_allow_the_building_finding():
    c = case("finding-on-the-building-not-the-landlord")
    bad = fake_turn("Yes, the owner was found to have harassed tenants after a trial in 2016.")
    assert check_deterministic({"must_not_assert": c["must_not_assert"], "summary_must_not_assert": c["summary_must_not_assert"]}, bad, bad)
    ok = fake_turn("A case on the building has a recorded harassment finding, After Trial, dated 2016. The respondent, McLORD OBIOHA, "
                   "does not match the registered owner name; the records do not say the owner was found to have harassed anyone.")
    assert check_deterministic({"must_not_assert": c["must_not_assert"], "summary_must_not_assert": c["summary_must_not_assert"]}, ok, ok) == []


def test_the_rate_pattern_rejects_a_zero_rate_and_accepts_unavailable():
    c = case("rate-unavailable-is-not-zero")
    assert re_search(c["must_match"][0], "The rate per unit is unavailable because the lot has 0 residential units.")
    assert not re_search(c["must_match"][0], "The rate is 0.0 open violations per unit.")


def re_search(pattern: str, text: str) -> bool:
    import re
    return re.search(pattern, text, re.I) is not None


def test_the_severity_patterns_allow_the_denial_and_reject_a_rating():
    c = case("how-bad-is-it-is-not-a-severity")
    denial = fake_turn("Violations are what was cited, and the records do not give a severity rating.")
    assert check_deterministic({k: c[k] for k in ("must_not_match", "must_not_assert")}, denial, denial) == []   # the live answer of 2026-11-25
    rated = fake_turn("The severity rating is high, a high severity building.")
    assert check_deterministic({k: c[k] for k in ("must_not_match",)}, rated, rated)


def test_the_prompt_keeps_registered_owners_to_litigation_answers():
    from watchline.agent.agent import system_prompt
    assert "`registered_owners` is only for `litigation_cases`" in " ".join(system_prompt().split())


def test_the_severity_patterns_reject_a_rating():
    c = case("how-bad-is-it-is-not-a-severity")
    bad = fake_turn("Conditions are dangerous: a severity score of high, with 4 open violations in total.")
    failures = check_deterministic({k: c[k] for k in ("must_not_match", "must_not_assert")}, bad, bad)
    assert len(failures) >= 2


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
    yield dict(client=client, graph=Neo4jGraph(driver, db), pg=Neo4jProfileGraph(driver, db), rg=Neo4jTimelineGraph(driver, db),
               judge=judge_llm, model=agent_llm, guard=eval_guard, results=results)
    driver.close()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"slices-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"agent_model": AGENT_MODEL, "judge_model": JUDGE_MODEL, "cases": results}, indent=1))


@pytest.mark.llm
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_agent_eval_slices(world, case):
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


# ---- fixes from the first live run (2026-11-25): the model cited the wrong tool's section, subtracted a count, and a hedge was missed ----------

def test_a_hedge_of_the_form_not_a_finding_that_excuses_the_same_party_phrase():
    c = case("respondent-matching-the-owner-is-a-lead")
    hedged = fake_turn("The respondent BEAVER STREET COMMONS LLC matches the registered owner name by rule N1; this is a lead, not a finding that they are the same party.")
    assert check_deterministic({"must_not_assert": c["must_not_assert"]}, hedged, hedged) == []
    claim = fake_turn("The respondent and the registered owner are the same company.")
    assert check_deterministic({"must_not_assert": c["must_not_assert"]}, claim, claim)


def test_a_denial_that_the_records_say_which_respondent_is_the_owner_is_a_hedge():
    """The second live run (2026-11-25) wrote this sentence; it denies the claim the pattern looks for."""
    c = case("respondent-matching-the-owner-is-a-lead")
    said = ("The respondent BEAVER STREET COMMONS LLC matches the registered owner name Beaver Street Commons LLC by a normalized name comparison "
            "(rule N1); this is a lead, not a confirmed identity, and the records do not record which respondent is the owner.")
    assert check_deterministic({"must_not_assert": c["must_not_assert"]}, fake_turn(said), fake_turn(said)) == []
    claim = "The records record that the respondent is the owner."
    assert check_deterministic({"must_not_assert": c["must_not_assert"]}, fake_turn(claim), fake_turn(claim))


def test_the_model_can_point_at_the_owner_names_in_a_litigation_answer():
    from test_agent_tools import FakeClient, FakeGraph, resolved
    from test_conditions import FakeCG
    from test_conditions import case as lit_case

    from watchline.agent import tools as T
    from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact, assemble
    out = T.make_litigation_cases_tool(FakeClient(resolved()), FakeGraph(), FakeCG(cases=[lit_case()], owners=[dict(name="ACME LLC")])).invoke(
        {"address": "1 Main St", "borough": "Manhattan"})
    a = assemble(ModelAnswer(kind="litigation", summary="One case.", facts=[
        ModelFact(statement="The registered owner is ACME LLC.", evidence=[EvidenceRef(section="registered_owners")])]), [out])
    assert not a.facts[0].unresolved and a.facts[0].evidence[0].data == ["ACME LLC"]


def test_the_prompt_says_which_section_each_new_tool_feeds_and_forbids_subtracting_counts():
    from watchline.agent.agent import system_prompt
    text = " ".join(system_prompt().split())
    assert "`deeds` is only for `deed_vs_owner`" in text and "`characteristics` is only for `building_profile`" in text
    assert "`owners` is only for `deed_vs_owner`" in text and "Never subtract one count from another" in text
    from test_agent_tools import FakeClient, FakeGraph, resolved

    from watchline.agent import tools as T
    from watchline.deeds.timeline import Neo4jTimelineGraph
    desc = " ".join(T.make_deed_timeline_tool(FakeClient(resolved()), FakeGraph(), Neo4jTimelineGraph.__new__(Neo4jTimelineGraph)).description.split())
    assert "never subtract one from another" in desc
