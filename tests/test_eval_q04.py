"""Q4 evals at the tool level: call the building_contacts tool against the live sidecar and graph and check what the model sees.

Cases live in tests/evals/q04_cases.yaml; expected values come from live probes, not from the spec. No model is called.
"""
import os
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.agent.tools import make_building_contacts_tool
from watchline.deeds.timeline import Neo4jTimelineGraph
from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph

load_dotenv()

CASES = yaml.safe_load((Path(__file__).parent / "evals" / "q04_cases.yaml").read_text())
FORBIDDEN_KEYS = {"owner_of_building", "title_holder", "same_party", "same_owner", "is_owner", "total", "score"}


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
    yield make_building_contacts_tool(client, Neo4jGraph(driver, db), Neo4jTimelineGraph(driver, db))
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
    if "contacts" in expect:
        got = {str(g["registrationId"]): [[c["role"], c["name"], c["title"], c["mailingAddress"]] for c in g["contacts"]]
               for b in out["contact_buildings"] for g in b["registrations"]}
        assert got == expect["contacts"], got
    codes = {c["code"] for c in out.get("caveats", [])}
    assert set(expect.get("caveat_codes", [])) <= codes, f"caveat codes {codes}"
    assert not set(expect.get("caveat_codes_absent", [])) & codes, f"caveat codes {codes}"


def check_ontology(out: dict):
    """No contact is called the owner or merged with another record, and an answer with contacts names HPD as its source."""
    assert not FORBIDDEN_KEYS & set(keys_anywhere(out))
    if any(g["contacts"] for b in out.get("contact_buildings", []) for g in b["registrations"]):
        assert "role_as_recorded" in {c["code"] for c in out["caveats"]}
        assert any("HPD" in s for s in out["sources"])


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_live_eval_q04(live, case):
    out = live.invoke(case["input"])
    check(out, case["expect"])
    check_ontology(out)
