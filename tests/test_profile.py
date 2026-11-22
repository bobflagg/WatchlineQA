import os

import httpx
import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Answer, Match, Neo4jGraph
from watchline.profile.profile import (
    CAVEAT_COUNTS,
    CAVEAT_UNREGISTERED,
    Neo4jProfileGraph,
    build_profile,
    building_profile,
)

load_dotenv()

LOT = dict(bbl="1000010001", address="1 MAIN ST", yearBuilt=1931, buildingClass="C1", unitsRes=24,
           assessedTotal=1000, plutoNumBuildings=2, hpdRegistered=True)


class FakePG:
    def __init__(self, lot=LOT, buildings=(), violations=(), problems=(), litigation=()):
        self._lot, self._b = lot, list(buildings)
        self._v, self._p, self._l = list(violations), list(problems), list(litigation)

    def lot(self, bbl): return self._lot
    def buildings(self, bbl): return self._b
    def violations(self, bbl): return self._v
    def problems(self, bbl): return self._p
    def litigation(self, bbl): return self._l


def answer(**kw):
    base = dict(input="1 Main St", outcome=Match.EXACT, bbl="1000010001", bin="1", in_graph=True)
    return Answer(**{**base, **kw})


BUILDINGS = [dict(bin="1", address="1 MAIN ST"), dict(bin="2", address="3 MAIN ST")]


@pytest.mark.parametrize("outcome", [Match.AMBIGUOUS, Match.NOT_FOUND, Match.UNAVAILABLE])
def test_unresolved_returns_resolution_only(outcome):
    p = build_profile(answer(outcome=outcome, bbl=None, in_graph=None), FakePG())
    assert p.lot is None and p.buildings == ()


def test_lot_not_in_graph_returns_resolution_only():
    p = build_profile(answer(in_graph=False), FakePG())
    assert p.lot is None and p.buildings == ()


def test_addressed_building_flagged_and_counts_by_type():
    pg = FakePG(buildings=BUILDINGS,
                violations=[dict(bin="2", violationClass="A", status="Close", n=1),
                            dict(bin="2", violationClass="B", status="Close", n=2)],
                problems=[dict(bin="1", majorCategory="HEAT", duplicate=False, n=5),
                          dict(bin="1", majorCategory="HEAT", duplicate=True, n=2)],
                litigation=[dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding="After Trial", n=1),
                            dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding="No Harassment", n=2)])
    p = build_profile(answer(), pg)
    one, two = p.buildings
    assert one.addressed and not two.addressed
    assert two.violations == {("A", "Close"): 1, ("B", "Close"): 2}   # by class, never a single total
    assert one.problems == {("HEAT", False): 5, ("HEAT", True): 2}     # duplicates counted separately
    assert one.litigation == {("Tenant Action", "CLOSED"): 3}
    assert one.harassment_findings == 1                                # only After Inquest / After Trial
    assert p.lot_totals()["violations"] == {("A", "Close"): 1, ("B", "Close"): 2}


def test_lot_wide_values_stay_on_lot():
    p = build_profile(answer(), FakePG(buildings=BUILDINGS))
    assert p.lot["unitsRes"] == 24
    assert not hasattr(p.buildings[0], "unitsRes")


def test_two_building_counts_differ_caveat():
    p = build_profile(answer(), FakePG(buildings=BUILDINGS[:1]))
    assert p.buildings_listed == 1 and p.lot["plutoNumBuildings"] == 2
    assert CAVEAT_COUNTS.format(pluto=2, listed=1) in p.caveats


def test_unregistered_lot_says_no_building_recorded():
    p = build_profile(answer(bin=None), FakePG(lot={**LOT, "hpdRegistered": False}, buildings=[]))
    assert p.buildings == () and CAVEAT_UNREGISTERED in p.caveats


def test_variant_and_related_lots_caveats():
    p = build_profile(answer(outcome=Match.VARIANT, tried=("1 MAIN STREET",), related_lots=("1000010002",)),
                      FakePG(buildings=BUILDINGS))
    assert any("variant" in c for c in p.caveats)
    assert any("1000010002" in c for c in p.caveats)


# ---- live: real Geosupport sidecar and Neo4j (anchors from specs/questions/q01.md) -----------------------------

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
    yield client, Neo4jGraph(driver, db), Neo4jProfileGraph(driver, db)
    driver.close()


def test_live_multi_building_lot_anchor_d(live):
    client, graph, pg = live
    p = building_profile(client, graph, pg, "224 54 Street, Brooklyn")
    assert p.resolution.bbl == "3008210012"
    assert {b.bin for b in p.buildings} == {"3324448", "3324450", "3324451"}
    assert [b.bin for b in p.buildings if b.addressed] == ["3324451"]
    assert p.lot["unitsRes"] == 18 and p.lot["plutoNumBuildings"] == 3 and p.buildings_listed == 3


def test_live_single_building_lot_anchor_a(live):
    client, graph, pg = live
    p = building_profile(client, graph, pg, "5413 7 Avenue, Brooklyn")
    assert p.resolution.bbl == "3008260002"
    assert [b.bin for b in p.buildings] == ["3014788"] and p.lot["unitsRes"] == 32


def test_live_pluto_counts_more_buildings_than_hpd_lists(live):
    client, graph, pg = live
    p = building_profile(client, graph, pg, "17 Battery Place, Manhattan")
    assert p.resolution.bbl == "1000157501"
    assert p.lot["plutoNumBuildings"] == 2 and p.buildings_listed == 1
    assert CAVEAT_COUNTS.format(pluto=2, listed=1) in p.caveats
