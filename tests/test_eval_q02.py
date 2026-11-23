"""Q2 evals at the tool level: call the registered_owner tool against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q02_cases.yaml; expected values come from live probes, not from the spec.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_registered_owner_tool
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.registration.registration import Neo4jRegistrationGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "q02_cases.yaml").read_text())
FORBIDDEN_KEYS = {"owner", "owners_of_building", "title_holder", "deed_owner", "current_owner", "total", "score"}


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
    yield make_registered_owner_tool(client, Neo4jGraph(driver, db), Neo4jRegistrationGraph(driver, db))
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
    buildings = out.get("registration_buildings", [])
    if "status" in expect:
        assert out["status"] == expect["status"], out
    if "outcome" in expect:
        assert res["outcome"] == expect["outcome"]
    if "bbl" in expect:
        assert res["bbl"] == expect["bbl"]
    if "bins" in expect:
        assert sorted(b["bin"] for b in buildings) == sorted(expect["bins"])
    if "addressed_bin" in expect:
        assert [b["bin"] for b in buildings if b["addressed"]] == [expect["addressed_bin"]]
    if expect.get("no_buildings"):
        assert buildings == []
    for bin_, regs in expect.get("registrations", {}).items():
        got = {g["registrationId"]: g for b in buildings if b["bin"] == bin_ for g in b["registrations"]}
        assert set(got) == set(regs), f"{bin_}: registrations {sorted(got)} != {sorted(regs)}"
        for rid, (last, end, owners) in regs.items():
            g = got[rid]
            assert (g["lastRegistered"], g["registrationEnd"]) == (last, end), f"{rid}: dates {g}"
            assert len(g["owners"]) == len(owners), f"{rid}: owners {g['owners']}"
            for (type_, name), o in zip(owners, g["owners"]):
                assert o["contactType"] == type_, f"{rid}: owner {o}"
                if name is not None:                      # null: individuals' names are not written into the cases
                    assert o["name"] == name, f"{rid}: owner {o}"
    codes = {c["code"] for c in out.get("caveats", [])}
    assert set(expect.get("caveat_codes", [])) <= codes, f"caveat codes {codes}"
    assert not set(expect.get("caveat_codes_absent", [])) & codes, f"caveat codes {codes}"
    text = " ".join(c["text"] for c in out.get("caveats", [])) + " " + out.get("message", "")
    for s in expect.get("caveats_contain", []):
        assert s in text, f"missing caveat text {s!r} in {text!r}"
    for s in expect.get("caveats_absent", []):
        assert s not in text, f"unexpected caveat text {s!r}"


def check_ontology(out: dict):
    """Rules that hold for every answer: a registrant is not an owner of record, every building keeps its own registrations,
    and dates belong to the registration, never the building."""
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out)), "no key may call a registrant the owner or sum anything"
    assert "buildings" not in out, "registration results use registration_buildings, so a profile reference cannot match them"
    for b in out.get("registration_buildings", []):
        assert not {"lastRegistered", "registrationEnd", "owners"} & set(b), "dates and owners belong to the registration"
        for g in b["registrations"]:
            assert {"registrationId", "lastRegistered", "registrationEnd", "owners"} == set(g)
            assert all(o["contactType"] in ("CorporateOwner", "IndividualOwner", "JointOwner") for o in g["owners"])
    if out.get("registration_buildings"):
        assert {"registrant_not_title", "registration_period", "owner_not_other_roles"} <= {c["code"] for c in out["caveats"]}
    if out["status"] == "ok":
        assert out["sources"], "an answer names its sources"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_eval_q02(live, case):
    out = live.invoke(case["input"])
    check(out, case["expect"])
    check_ontology(out)
