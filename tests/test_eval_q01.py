"""Q1 evals at the tool level: call the agent tool against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q01_cases.yaml. Agent-level evals (does the model relay the caveats) come with the agent.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_building_profile_tool
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile.profile import Neo4jProfileGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "q01_cases.yaml").read_text())
FORBIDDEN_KEYS = {"total", "score", "severity", "total_violations", "total_problems", "total_litigation"}
LOT_WIDE = {"unitsRes", "assessedTotal", "yearBuilt", "buildingClass", "plutoNumBuildings"}
GROUPS = ("violations", "problems", "litigation")


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
    pg = Neo4jProfileGraph(driver, db)
    yield make_building_profile_tool(client, Neo4jGraph(driver, db), pg), pg
    driver.close()


def keys_anywhere(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from keys_anywhere(v)
    elif isinstance(node, list):
        for v in node:
            yield from keys_anywhere(v)


def count_value(out, name):
    return next(c["value"] for c in out["counts"] if c["name"] == name)


def check(out: dict, expect: dict):
    res = out.get("resolution", {})
    if "status" in expect:
        assert out["status"] == expect["status"], out
    if "outcome" in expect:
        assert res["outcome"] == expect["outcome"]
    if "bbl" in expect:
        assert res["bbl"] == expect["bbl"]
    if "bins" in expect:
        assert sorted(b["bin"] for b in out["buildings"]) == sorted(expect["bins"])
    if "addressed_bin" in expect:
        assert [b["bin"] for b in out["buildings"] if b["addressed"]] == [expect["addressed_bin"]]
    if "pluto_count" in expect:
        assert count_value(out, "buildings (PLUTO)") == expect["pluto_count"]
    if "hpd_count" in expect:
        assert count_value(out, "buildings (HPD)") == expect["hpd_count"]
    if "units" in expect:
        assert out["lot"]["unitsRes"] == expect["units"]
    for key, field in (("year_built", "yearBuilt"), ("building_class", "buildingClass"), ("assessed_total", "assessedTotal")):
        if key in expect:
            assert out["lot"][field] == expect[key]
    if "inferred" in expect:
        assert res["inferred"] is expect["inferred"]
    if "min_candidates" in expect:
        assert len(set(res["candidates"])) >= expect["min_candidates"]
    for bin_, n in expect.get("harassment_by_bin", {}).items():
        got = next(b for b in out["buildings"] if b["bin"] == bin_)["harassment_findings_after_inquest_or_trial"]
        assert got == n, f"{bin_}: {got} harassment findings, expected {n}"
    if "related_lots" in expect:
        assert set(expect["related_lots"]) <= set(res["related_lots"])
    for name in expect.get("candidates_include", []):
        assert any(name in c for c in res["candidates"])
    caveats = " ".join(c["text"] for c in out.get("caveats", [])) + " " + out.get("message", "")
    for s in expect.get("caveats_contain", []):
        assert s in caveats, f"missing caveat text {s!r} in {caveats!r}"
    for s in expect.get("caveats_absent", []):
        assert s not in caveats, f"unexpected caveat text {s!r}"


def group_rows(out: dict) -> dict:
    """(group, key tuple) -> n summed over the buildings shown."""
    sums: dict = {}
    for b in out["buildings"]:
        for g in GROUPS:
            for row in b[g]:
                key = (g, tuple(sorted((k, v) for k, v in row.items() if k != "n")))
                sums[key] = sums.get(key, 0) + row["n"]
    return sums


def check_ontology(out: dict):
    """Rules that hold for every answer: counts by class or type only, lot-wide values only on the lot."""
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out)), "counts must never be summed into a total or score"
    outside_lot = {k: v for k, v in out.items() if k not in ("lot",)}
    assert not LOT_WIDE & set(keys_anywhere(outside_lot)), "lot-wide values belong to the lot, never a building"
    for c in out.get("counts", []):
        assert c["unit"] and c["source"], "every count names its unit and source"
    assert [c["name"] for c in out.get("counts", [])] in ([], ["parcels", "buildings (PLUTO)", "buildings (HPD)", "residential units"])
    if out.get("lot") is None:
        return
    assert any("not findings of fault" in c["text"] for c in out["caveats"])
    # every count row is a (class or type) group: it has a key besides n, and no row is a bare number
    for b in out["buildings"]:
        for g in GROUPS:
            assert all(len(row) >= 2 for row in b[g])
    # totals are the same-group sums of the building rows: never one number across classes. Compared only when all shown.
    totals = {(g, tuple(sorted((k, v) for k, v in row.items() if k != "n"))): row["n"]
              for g in GROUPS for row in out["totals_across_all_listed_buildings"][g]}
    if len(out["buildings"]) == out["buildings_listed"]:
        assert totals == group_rows(out)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_eval_q01(live, case):
    tool, _ = live
    out = tool.invoke(case["input"])
    check(out, case["expect"])
    check_ontology(out)


def test_live_eval_harassment_counts_match_direct_graph_counts(live):
    """The tool's per-building harassment count equals a direct count of After Inquest / After Trial cases."""
    tool, pg = live
    out = tool.invoke({"address": "21-08 Nameoke Avenue, Queens"})
    assert out["status"] == "ok" and out["buildings"]
    for b in out["buildings"]:
        direct = pg._read("CYPHER 25 MATCH (:Building {bin: $bin})-[:HAS_LITIGATION]->(t:Litigation) "
                          "WHERE t.harassmentFinding IN ['After Inquest', 'After Trial'] RETURN count(t) AS n", bin=b["bin"])[0]["n"]
        assert b["harassment_findings_after_inquest_or_trial"] == direct
    assert sum(b["harassment_findings_after_inquest_or_trial"] for b in out["buildings"]) >= 1   # a case that has findings
