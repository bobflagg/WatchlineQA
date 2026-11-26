import os

import pytest

from watchline.schema.check import Actual, compare

NODES = {"Lot": {"bbl", "unitsRes"}}
RELS = {"HAS_BUILDING": [("Lot", "Building", set())], "COVERS": [("Landlord", "Lot", {"weight"})]}


def actual(**kw):
    base = dict(node_props={"Lot": {"bbl", "unitsRes"}, "Building": set(), "Landlord": set()},
                rel_props={"HAS_BUILDING": set(), "COVERS": {"weight"}},
                rel_ends={"HAS_BUILDING": {("Lot", "Building")}, "COVERS": {("Landlord", "Lot")}})
    return Actual(**{**base, **kw})


def test_all_present():
    assert compare(NODES, RELS, actual()) == []


def test_missing_label_with_hint():
    out = compare(NODES, RELS, actual(node_props={"Lots": {"bbl", "unitsRes"}}))
    assert out == ["label 'Lot' is missing (did you mean 'Lots'?)"]


def test_renamed_property_hint():
    out = compare(NODES, RELS, actual(node_props={"Lot": {"bbl", "unitsResidential"}}))
    assert out == ["label 'Lot' has no property 'unitsRes' (did you mean 'unitsResidential'?)"]


def test_missing_relationship_type_and_wrong_ends():
    out = compare(NODES, RELS, actual(rel_ends={"COVERS": {("Landlord", "Building")}}))
    assert any("'HAS_BUILDING' is missing" in p for p in out)
    assert any("'COVERS' does not run from 'Landlord' to 'Lot'" in p for p in out)


def test_missing_relationship_property():
    out = compare(NODES, RELS, actual(rel_props={"HAS_BUILDING": set(), "COVERS": set()}))
    assert out == ["relationship 'COVERS' has no property 'weight'"]


def test_live_schema_matches_code():
    """Needs Neo4j; skips when unreachable."""
    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    from watchline.schema.check import read_actual
    load_dotenv()
    uri, user, pw, db = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE"))
    if not (uri and user and pw and db):
        pytest.skip("NEO4J_* not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
        problems = compare(actual=read_actual(driver, db))
    except Exception as exc:
        if type(exc).__module__.startswith("neo4j"):
            pytest.skip(f"Neo4j not reachable: {exc}")
        raise
    finally:
        driver.close()
    assert problems == []
