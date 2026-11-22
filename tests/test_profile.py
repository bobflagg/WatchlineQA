import os

import httpx
import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase, Query

from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Answer, Match, Neo4jGraph
from watchline.profile import profile as P
from watchline.profile.profile import Neo4jProfileGraph, build_profile, building_profile

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


def count(p, name):
    return next(c for c in p.counts if c.name == name)


# ---- resolution short-circuits: nothing to profile, but the reason is stated -----------------------------------

@pytest.mark.parametrize("kw, expected", [
    (dict(outcome=Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("MAIN ST", "MAIN AVE")), P.CAVEAT_AMBIGUOUS),
    (dict(outcome=Match.NOT_FOUND, bbl=None, in_graph=None, grc="42", tried=("1 MAIN ST",)),
     P.CAVEAT_NOT_FOUND.format(grc="42", tried="1 MAIN ST")),
    (dict(outcome=Match.UNAVAILABLE, bbl=None, in_graph=None), P.CAVEAT_UNAVAILABLE),
    (dict(in_graph=False), P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001")),
])
def test_unresolved_returns_resolution_and_reason(kw, expected):
    p = build_profile(answer(**kw), FakePG())
    assert p.lot is None and p.buildings == () and p.counts == ()
    assert expected in p.caveats


def test_lot_missing_from_graph_after_resolution():
    p = build_profile(answer(), FakePG(lot=None))
    assert p.lot is None and P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001") in p.caveats


# ---- content ---------------------------------------------------------------------------------------------------

def test_addressed_building_flagged_and_counts_by_type():
    pg = FakePG(buildings=BUILDINGS,
                violations=[dict(bin="2", violationClass="A", status="Close", n=1),
                            dict(bin="2", violationClass="B", status="Close", n=2)],
                problems=[dict(bin="1", majorCategory="HEAT", duplicate=False, n=5),
                          dict(bin="1", majorCategory="HEAT", duplicate=True, n=2)],
                litigation=[dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding="After Trial", n=1),
                            dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding="No Harassment", n=2),
                            dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding=None, n=4)])
    p = build_profile(answer(), pg)
    one, two = p.buildings
    assert one.addressed and not two.addressed
    assert two.violations == {("A", "Close"): 1, ("B", "Close"): 2}   # by class, never a single total
    assert one.problems == {("HEAT", False): 5, ("HEAT", True): 2}     # duplicates counted separately
    assert one.litigation == {("Tenant Action", "CLOSED"): 7}
    assert one.harassment_findings == 1                                # only After Inquest / After Trial
    totals = p.lot_totals()
    assert totals["violations"] == {("A", "Close"): 1, ("B", "Close"): 2}
    assert totals["problems"] == {("HEAT", False): 5, ("HEAT", True): 2}
    assert totals["litigation"] == {("Tenant Action", "CLOSED"): 7}
    for c in (P.CAVEAT_CITED, P.CAVEAT_DUPLICATES, P.CAVEAT_HARASSMENT):
        assert c in p.caveats


def test_harassment_caveat_does_not_call_no_harassment_unfound():
    assert "No Harassment" in P.CAVEAT_HARASSMENT and "not found" not in P.CAVEAT_HARASSMENT


def test_lot_wide_values_stay_on_lot_and_are_labelled():
    p = build_profile(answer(), FakePG(buildings=BUILDINGS))
    assert p.lot["unitsRes"] == 24 and P.CAVEAT_LOT_WIDE in p.caveats
    fields = set(p.buildings[0].__dataclass_fields__)
    assert not fields & {"unitsRes", "assessedTotal", "yearBuilt", "buildingClass"}
    by_name = {c.name: c for c in p.characteristics}
    assert set(by_name) == {"yearBuilt", "buildingClass", "unitsRes", "assessedTotal"}
    assert "lot-wide" in by_name["unitsRes"].source and "26v1" in by_name["yearBuilt"].source


def test_counts_are_separate_and_name_unit_and_source():
    p = build_profile(answer(), FakePG(buildings=BUILDINGS[:1]))
    parcels, pluto, hpd, units = (count(p, n) for n in ("parcels", "buildings (PLUTO)", "buildings (HPD)",
                                                         "residential units"))
    assert (parcels.value, pluto.value, hpd.value, units.value) == (1, 2, 1, 24)
    assert "PLUTO" in pluto.source and "HPD" in hpd.source and "BINs" in hpd.unit
    assert p.buildings_listed == 1
    assert P.CAVEAT_COUNTS.format(pluto=2, listed=1) in p.caveats


def test_no_hpd_buildings_unregistered_vs_registered():
    unreg = build_profile(answer(bin=None), FakePG(lot={**LOT, "hpdRegistered": False}, buildings=[]))
    assert unreg.buildings == () and P.CAVEAT_NO_BUILDING in unreg.caveats
    assert not any(c.startswith("Two building counts") for c in unreg.caveats)   # not both
    reg = build_profile(answer(bin=None), FakePG(buildings=[]))
    assert P.CAVEAT_REGISTERED_NO_BUILDING in reg.caveats and P.CAVEAT_NO_BUILDING not in reg.caveats


def test_missing_pluto_count_is_not_printed_as_none():
    p = build_profile(answer(), FakePG(lot={**LOT, "plutoNumBuildings": None}, buildings=BUILDINGS))
    assert not any("None" in c for c in p.caveats)
    assert P.CAVEAT_PLUTO_COUNT_MISSING.format(listed=2) in p.caveats


def test_addressed_building_missing_is_stated():
    p = build_profile(answer(bin="9"), FakePG(buildings=BUILDINGS))
    assert not any(b.addressed for b in p.buildings) and P.CAVEAT_NO_ADDRESSED.format(bin="9") in p.caveats
    p = build_profile(answer(bin=None), FakePG(buildings=BUILDINGS))
    assert P.CAVEAT_NO_ADDRESSED_BIN in p.caveats


def test_variant_caveat_reports_returned_address_and_grc():
    res = answer(outcome=Match.VARIANT, input="54 ST", returned="54 STREET", grc="01", tried=("54 ST", "54 STREET"))
    p = build_profile(res, FakePG(buildings=BUILDINGS))
    assert P.CAVEAT_VARIANT.format(typed="54 ST", returned="54 STREET", grc="01") in p.caveats


def test_inferred_and_neighborhood_caveats():
    res = answer(outcome=Match.VARIANT, inferred=True, tried=("1 MAIN ST", "1 MAIN STREET"), returned="1 MAIN STREET",
                 borough_inferred_from="Park Slope")
    p = build_profile(res, FakePG(buildings=BUILDINGS))
    assert P.CAVEAT_INFERRED.format(tried="1 MAIN ST, 1 MAIN STREET") in p.caveats
    assert P.CAVEAT_HOOD.format(hood="Park Slope") in p.caveats


def test_related_lots_caveat_says_not_additive():
    p = build_profile(answer(related_lots=("1000010002",)), FakePG(buildings=BUILDINGS))
    caveat = next(c for c in p.caveats if "1000010002" in c)
    assert "not additive" in caveat


def test_truncation_is_stated():
    rows = [dict(bin="1", violationClass=str(i), status="Open", n=1) for i in range(P.MAX_GROUPS)]
    p = build_profile(answer(), FakePG(buildings=BUILDINGS, violations=rows))
    assert P.CAVEAT_TRUNCATED in p.caveats


def test_queries_carry_a_timeout_and_are_read_routed():
    seen = []

    class FakeResult:
        records = []

    class FakeDriver:
        def execute_query(self, query, params=None, **kw):
            seen.append((query, kw))
            return FakeResult()

    pg = Neo4jProfileGraph(FakeDriver(), "watchline")
    pg.lot("1"), pg.buildings("1"), pg.violations("1"), pg.problems("1"), pg.litigation("1")
    assert len(seen) == 5
    for query, kw in seen:
        assert isinstance(query, Query) and query.timeout == P.TIMEOUT_S
        assert kw["routing_"].value == "r" and "timeout" not in kw


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
    assert p.resolution.outcome is Match.EXACT and not any("variant" in c for c in p.caveats)
    # summaries read from the graph: 218/220 54 St (3324450) has one closed violation in each of classes A, B, C
    by_bin = {b.bin: b for b in p.buildings}
    assert by_bin["3324450"].violations == {("A", "Close"): 1, ("B", "Close"): 1, ("C", "Close"): 1}
    assert by_bin["3324448"].violations == {}


def test_live_variant_reports_typed_and_returned_address(live):
    client, graph, pg = live
    p = building_profile(client, graph, pg, "224 54th St, Brooklyn")
    assert p.resolution.outcome is Match.VARIANT and p.resolution.bbl == "3008210012"
    assert P.CAVEAT_VARIANT.format(typed="224 54th St", returned="224 54 STREET", grc="00") in p.caveats


def test_live_summaries_match_graph_counts(live):
    """Problems and litigation queries run for real: per-building totals equal direct counts."""
    client, graph, pg = live
    p = building_profile(client, graph, pg, "224 54 Street, Brooklyn")
    for b in p.buildings:
        direct_p = pg._read("CYPHER 25 MATCH (:Building {bin: $bin})-[:HAS_PROBLEM]->(x) RETURN count(x) AS n", bin=b.bin)[0]["n"]
        direct_l = pg._read("CYPHER 25 MATCH (:Building {bin: $bin})-[:HAS_LITIGATION]->(x) RETURN count(x) AS n", bin=b.bin)[0]["n"]
        assert sum(b.problems.values()) == direct_p and sum(b.litigation.values()) == direct_l


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
    assert P.CAVEAT_COUNTS.format(pluto=2, listed=1) in p.caveats


def test_live_unregistered_lot_has_no_building_and_says_so(live):
    client, graph, pg = live
    p = building_profile(client, graph, pg, "70 Broad Street, Manhattan")
    assert p.resolution.bbl == "1000110015" and p.lot["hpdRegistered"] is False
    assert p.buildings == () and p.buildings_listed == 0
    assert P.CAVEAT_NO_BUILDING in p.caveats
    assert count(p, "buildings (HPD)").value == 0
