"""Q12.1 evals at the tool level: call the deed_timeline tool against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q12_cases.yaml; expected values come from live probes, not from the spec. No model is called.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_deed_timeline_tool
from watchline.deeds.timeline import Neo4jTimelineGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "q12_cases.yaml").read_text())
FORBIDDEN_KEYS = {"owner_of_building", "title_holder", "same_party", "same_owner", "is_owner", "sale", "price", "total", "score"}


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
    yield make_deed_timeline_tool(client, Neo4jGraph(driver, db), Neo4jTimelineGraph(driver, db))
    driver.close()


def keys_anywhere(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys_anywhere(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys_anywhere(v)


def check(out: dict, expect: dict):
    if "status" in expect:
        assert out["status"] == expect["status"], out
    if "bbl" in expect:
        assert out["resolution"]["bbl"] == expect["bbl"]
    deeds = {d["documentId"]: d for d in out.get("timeline", [])}
    if "ids" in expect:
        assert [d["documentId"] for d in out["timeline"]] == expect["ids"]
    if "counts" in expect:
        c = out["timeline_counts"]
        assert {k: c[k] for k in ("deeds", "notSale", "amountZero", "withAmount", "byType")} == expect["counts"]
    for doc, n in expect.get("other_lots", {}).items():
        assert deeds[doc]["otherLots"] == n
    for doc, names in expect.get("grantees", {}).items():
        assert deeds[doc]["grantees"] == names
    for doc, n in expect.get("grantee_rows", {}).items():
        assert deeds[doc]["granteeRows"] == n
    codes = {c["code"] for c in out.get("caveats", [])}
    assert set(expect.get("caveat_codes", [])) <= codes, f"caveat codes {codes}"
    assert not set(expect.get("caveat_codes_absent", [])) & codes, f"caveat codes {codes}"


def check_ontology(out: dict):
    """A deed is never called a sale, nothing is summed into one figure, no party is called the owner, and the ACRIS source is named."""
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out))
    if out.get("timeline"):
        assert {"timeline_by_recorded", "party_names_as_recorded"} <= {c["code"] for c in out["caveats"]}
        assert any("ACRIS" in s for s in out["sources"])
        assert all(d["notSale"] for d in out["timeline"] if d["amount"] == 0)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_eval_q12(live, case):
    out = live.invoke(case["input"])
    check(out, case["expect"])
    check_ontology(out)
