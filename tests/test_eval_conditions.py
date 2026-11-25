"""Q15 and Q28 evals at the tool level: call open_violations and litigation_cases against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q15_cases.yaml and q28_cases.yaml; expected values come from live probes, not from the spec. No model is called.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_litigation_cases_tool, make_open_violations_tool
from watchline.conditions.conditions import Neo4jConditionsGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph

load_dotenv()

EVALS = Path(__file__).parent / "evals"
Q15 = yaml.safe_load((EVALS / "q15_cases.yaml").read_text())
Q28 = yaml.safe_load((EVALS / "q28_cases.yaml").read_text())
FORBIDDEN_KEYS = {"owner_of_building", "title_holder", "same_party", "same_owner", "is_owner", "total", "score", "severity", "grade"}


@pytest.fixture(scope="module")
def live():
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
    graph, cg = Neo4jGraph(driver, db), Neo4jConditionsGraph(driver, db)
    yield dict(violations=make_open_violations_tool(client, graph, cg), litigation=make_litigation_cases_tool(client, graph, cg))
    driver.close()


def keys_anywhere(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys_anywhere(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys_anywhere(v)


def check_common(out: dict, expect: dict):
    if "status" in expect:
        assert out["status"] == expect["status"], out
    if "bbl" in expect:
        assert out["resolution"]["bbl"] == expect["bbl"]
    codes = {c["code"] for c in out.get("caveats", [])}
    assert set(expect.get("caveat_codes", [])) <= codes, f"caveat codes {codes}"
    assert not set(expect.get("caveat_codes_absent", [])) & codes, f"caveat codes {codes}"
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out)), "nothing is called the owner, summed into a score or graded"


@pytest.mark.parametrize("case", Q15, ids=[c["id"] for c in Q15])
def test_live_eval_q15(live, case):
    out = live["violations"].invoke(case["input"])
    expect = case["expect"]
    check_common(out, expect)
    if "groups" in expect:
        got = {f"{g['violationClass']} {g['status']}": [g["n"], g["oldest"]] for b in out["violations"] for g in b["groups"]}
        assert got == {k: list(v) for k, v in expect["groups"].items()}, got
    if "oldest_open" in expect:
        assert [b["oldestOpen"] for b in out["violations"]] == [expect["oldest_open"]]
    if "rate" in expect:
        assert {k: out["violations_rate"][k] for k in ("open", "units", "perUnit")} == expect["rate"]
    if out["status"] == "ok" and out["lot"] is not None:
        assert any("HPD violations" in s for s in out["sources"])


@pytest.mark.parametrize("case", Q28, ids=[c["id"] for c in Q28])
def test_live_eval_q28(live, case):
    out = live["litigation"].invoke(case["input"])
    expect = case["expect"]
    check_common(out, expect)
    if "counts" in expect:
        assert out["case_counts"] == expect["counts"]
    if "owners" in expect:
        assert out["registered_owners"] == expect["owners"]
    by_id = {str(k["litigationId"]): k for k in out.get("cases", [])}
    for lid, exp in expect.get("cases", {}).items():
        k = by_id[lid]
        assert [k["caseType"], k["caseOpenDate"], k["caseStatus"], k["harassmentFinding"], k["findingDate"], k["penalty"],
                k["isHarassmentFinding"], k["respondentMatch"]] == exp
    for lid, resp in expect.get("respondents", {}).items():
        assert by_id[lid]["respondent"] == resp
    for lid, parts in expect.get("lead_parts", {}).items():
        assert [[m["part"], m["owner"], m["outcome"], m["rule"]] for m in by_id[lid]["matches"]] == parts
    for k in by_id.values():                              # only After Inquest or After Trial is ever a harassment finding
        assert k["isHarassmentFinding"] == (k["harassmentFinding"] in ("After Inquest", "After Trial"))
