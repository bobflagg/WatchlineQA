"""Q3 evals at the tool level: call the deed_vs_owner tool against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q03_cases.yaml; expected values come from live probes, not from the spec.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_deed_vs_owner_tool
from watchline.deeds.deeds import Neo4jDeedGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "q03_cases.yaml").read_text())
FORBIDDEN_KEYS = {"owner_of_building", "title_holder", "same_party", "same_owner", "is_owner", "sale", "price", "total", "score"}
NAME_OUTCOMES = {"exact_normalized", "normalization_match", "different", "not_comparable"}


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
    yield make_deed_vs_owner_tool(client, Neo4jGraph(driver, db), Neo4jDeedGraph(driver, db))
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
    res = out.get("resolution", {})
    if "status" in expect:
        assert out["status"] == expect["status"], out
    if "outcome" in expect:
        assert res["outcome"] == expect["outcome"]
    if "bbl" in expect:
        assert res["bbl"] == expect["bbl"]
    if expect.get("no_deeds"):
        assert out["deeds"] == []
    if "deeds" in expect:
        got = {d["documentId"]: [d["recordedDate"], d["docDate"], d["amount"], d["otherLots"], [g["name"] for g in d["grantees"]]]
               for d in out["deeds"]}
        assert got == {k: list(v) for k, v in expect["deeds"].items()}, got
    if "owners" in expect:
        assert [[o["contactType"], o["name"]] for o in out["owners"]] == expect["owners"]
    if "pairs" in expect:
        got = [[p["documentId"], p["grantee"], p["owner"], p["nameAgreement"]["outcome"], p["nameAgreement"]["rule"],
                p["addressAgreement"]["outcome"]] for p in out["comparison"]]
        assert got == expect["pairs"], got
    if "all_name_outcomes" in expect:
        assert out["comparison"] and {p["nameAgreement"]["outcome"] for p in out["comparison"]} == {expect["all_name_outcomes"]}
    codes = {c["code"] for c in out.get("caveats", [])}
    assert set(expect.get("caveat_codes", [])) <= codes, f"caveat codes {codes}"
    assert not set(expect.get("caveat_codes_absent", [])) & codes, f"caveat codes {codes}"
    text = " ".join(c["text"] for c in out.get("caveats", [])) + " " + out.get("message", "")
    for s in expect.get("caveats_contain", []):
        assert s in text, f"missing caveat text {s!r} in {text!r}"
    for s in expect.get("caveats_absent", []):
        assert s not in text, f"unexpected caveat text {s!r}"


def check_ontology(out: dict):
    """Rules that hold for every answer: agreement is a string comparison reported in two separate fields, nothing is called a sale or
    the owner, and no field merges a grantee with a registrant."""
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out)), "no key may call a party the owner, call a deed a sale, or sum anything"
    for p in out.get("comparison", []):
        assert p["nameAgreement"]["outcome"] in NAME_OUTCOMES and p["addressAgreement"]["outcome"] in {"same", "differs", "absent"}
        assert p["addressAgreement"]["rule"] == "A1"
    if out.get("comparison"):
        assert "name_match_not_identity" in {c["code"] for c in out["caveats"]}
    if out.get("deeds"):
        assert {"most_recent_by_recorded", "snapshots_differ"} <= {c["code"] for c in out["caveats"]}
    if out["status"] == "ok" and out["lot"] is not None:
        assert out["sources"], "an answer names its sources"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_eval_q03(live, case):
    out = live.invoke(case["input"])
    check(out, case["expect"])
    check_ontology(out)
