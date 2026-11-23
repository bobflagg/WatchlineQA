import os

import httpx
import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase, Query
from test_profile import LOT, answer

from watchline.geosupport.geosupport import Client
from watchline.geosupport.resolution import Neo4jGraph
from watchline.profile import profile as P
from watchline.registration import registration as R
from watchline.registration.registration import Neo4jRegistrationGraph, build_registrations, registered_owners

load_dotenv()


class FakeRG:
    def __init__(self, lot=LOT, rows=(), owners=()):
        self._lot, self._rows, self._owners = lot, list(rows), list(owners)

    def lot(self, bbl): return self._lot
    def registrations(self, bbl): return self._rows
    def owners(self, bbl): return self._owners


def row(bin_="1", rid=100, last="2025-09-30", end="2026-09-01", address="1 MAIN ST"):
    return dict(bin=bin_, address=address, registrationId=rid, lastRegistered=last, registrationEnd=end)


def owner(rid=100, kind="CorporateOwner", name="ACME LLC"):
    return dict(registrationId=rid, contactType=kind, name=name)


def codes(r):
    return {c.code for c in r.caveats}


# ---- resolution short-circuits ----------------------------------------------------------------------------------

@pytest.mark.parametrize("kw, expected", [
    (dict(outcome=P.Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("MAIN ST", "MAIN AVE")), P.CAVEAT_AMBIGUOUS),
    (dict(outcome=P.Match.UNAVAILABLE, bbl=None, in_graph=None), P.CAVEAT_UNAVAILABLE),
    (dict(in_graph=False), P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001")),
])
def test_unresolved_returns_resolution_and_reason(kw, expected):
    r = build_registrations(answer(**kw), FakeRG())
    assert r.lot is None and r.buildings == ()
    assert expected in r.caveats
    assert R.CAVEAT_NOT_TITLE not in r.caveats      # nothing was read, so no statement about registrations


def test_lot_missing_from_graph_after_resolution():
    r = build_registrations(answer(), FakeRG(lot=None))
    assert r.lot is None and P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001") in r.caveats


# ---- content ----------------------------------------------------------------------------------------------------

def test_single_registration_with_owner_and_dates():
    r = build_registrations(answer(), FakeRG(rows=[row()], owners=[owner()]))
    (b,) = r.buildings
    (reg,) = b.registrations
    assert b.bin == "1" and b.addressed
    assert (reg.registrationId, reg.lastRegistered, reg.registrationEnd) == (100, "2025-09-30", "2026-09-01")
    assert [(o.contactType, o.name) for o in reg.owners] == [("CorporateOwner", "ACME LLC")]
    assert {"registrant_not_title", "registration_period", "owner_not_other_roles"} <= codes(r)


def test_one_registration_per_building_on_a_multi_building_lot():
    rows = [row("1", 100), row("2", 200, address="3 MAIN ST")]
    owners = [owner(100, name="HP SUNSET PARK I HDFC INC."), owner(200, name="HP SUNSET PARK I HDFC INC")]
    r = build_registrations(answer(), FakeRG(rows=rows, owners=owners))
    one, two = r.buildings
    assert one.addressed and not two.addressed
    assert one.registrations[0].owners[0].name == "HP SUNSET PARK I HDFC INC."   # spellings reported as recorded
    assert two.registrations[0].owners[0].name == "HP SUNSET PARK I HDFC INC"


def test_several_registrations_for_one_building_are_all_listed():
    rows = [row("1", 11009, last=None, end="2025-09-01"), row("1", 11065, last="2026-01-08")]
    r = build_registrations(answer(), FakeRG(rows=rows, owners=[owner(11065, "IndividualOwner", "A PERSON")]))
    (b,) = r.buildings
    assert [g.registrationId for g in b.registrations] == [11009, 11065]
    assert b.registrations[0].lastRegistered is None            # absent, not guessed
    assert b.registrations[0].owners == ()                       # no owner contact: none inferred
    assert "no_owner_contact" in codes(r)


def test_joint_owners_are_all_listed_and_none_chosen():
    owners = [owner(100, name="HP PLAZA LLC"), owner(100, name="HP PLAZA LP")]
    r = build_registrations(answer(), FakeRG(rows=[row()], owners=owners))
    assert [o.name for o in r.buildings[0].registrations[0].owners] == ["HP PLAZA LLC", "HP PLAZA LP"]


def test_blank_owner_name_is_kept_with_name_absent():
    r = build_registrations(answer(), FakeRG(rows=[row()], owners=[owner(name=None)]))
    (o,) = r.buildings[0].registrations[0].owners
    assert o.contactType == "CorporateOwner" and o.name is None
    assert "owner_name_blank" in codes(r)


def test_exact_duplicate_owner_contacts_collapse():
    r = build_registrations(answer(), FakeRG(rows=[row()], owners=[owner(), owner()]))
    assert len(r.buildings[0].registrations[0].owners) == 1


def test_owners_attach_to_their_own_registration_only():
    rows = [row("1", 100), row("2", 200)]
    r = build_registrations(answer(), FakeRG(rows=rows, owners=[owner(200, name="B LLC")]))
    assert r.buildings[0].registrations[0].owners == ()
    assert r.buildings[1].registrations[0].owners[0].name == "B LLC"


def test_building_without_registration_is_listed_with_none_and_says_so():
    rows = [row("1", 100), dict(bin="2", address="3 MAIN ST", registrationId=None, lastRegistered=None, registrationEnd=None)]
    r = build_registrations(answer(), FakeRG(rows=rows, owners=[owner()]))
    assert r.buildings[1].registrations == ()
    assert "no_registration_found" in codes(r)


def test_lot_with_no_buildings_says_no_hpd_building_and_no_registration():
    r = build_registrations(answer(), FakeRG(lot={**LOT, "hpdRegistered": False}, rows=[]))
    assert r.buildings == ()
    assert P.CAVEAT_NO_BUILDING in r.caveats
    assert R.CAVEAT_NOT_TITLE not in r.caveats


def test_registered_lot_with_no_building_listed():
    r = build_registrations(answer(), FakeRG(rows=[]))
    assert P.CAVEAT_REGISTERED_NO_BUILDING in r.caveats


def test_no_addressed_building_is_stated():
    r = build_registrations(answer(bin="9"), FakeRG(rows=[row("1")], owners=[owner()]))
    assert not any(b.addressed for b in r.buildings)
    assert "no_addressed_building" in codes(r)


def test_truncation_at_the_row_limit_is_stated(monkeypatch):
    monkeypatch.setattr(R, "MAX_ROWS", 2)
    rows = [row("1", 100), row("2", 200)]
    r = build_registrations(answer(), FakeRG(rows=rows, owners=[owner()]))
    assert P.CAVEAT_TRUNCATED in r.caveats


def test_variant_match_caveat_carries_through():
    r = build_registrations(answer(outcome=P.Match.VARIANT, returned="1 MAIN STREET"), FakeRG(rows=[row()], owners=[owner()]))
    assert "variant_match" in codes(r)


def test_queries_carry_a_timeout_and_are_read_routed():
    seen = []

    class FakeResult:
        records = []

    class FakeDriver:
        def execute_query(self, query, params=None, **kw):
            seen.append((query, kw))
            return FakeResult()

    rg = Neo4jRegistrationGraph(FakeDriver(), "watchline")
    rg.lot("1"), rg.registrations("1"), rg.owners("1")
    assert len(seen) == 3
    for query, kw in seen:
        assert isinstance(query, Query) and query.timeout == P.TIMEOUT_S
        assert kw["routing_"].value == "r" and "timeout" not in kw


# ---- live: anchors probed on the live graph 2026-11-23 (specs/questions/q02.md values were provisional) -----------

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
    yield client, Neo4jGraph(driver, db), Neo4jRegistrationGraph(driver, db)
    driver.close()


def flat(r):
    return {g.registrationId: g for b in r.buildings for g in b.registrations}


def test_live_single_registration_anchor_a(live):
    client, graph, rg = live
    r = registered_owners(client, graph, rg, "5413 7 Avenue, Brooklyn")
    (b,) = r.buildings
    assert b.bin == "3014788" and b.addressed
    (g,) = b.registrations
    assert (g.registrationId, g.lastRegistered, g.registrationEnd) == (316103, "2025-09-30", "2026-09-01")
    assert [(o.contactType, o.name) for o in g.owners] == [("CorporateOwner", "5413 PLAZA LLC")]   # the Agent and officers are not owners


def test_live_co_op_anchor_c_name_as_hpd_spells_it(live):
    client, graph, rg = live
    r = registered_owners(client, graph, rg, "438 52 Street, Brooklyn")
    g = flat(r)[350423]
    assert (g.lastRegistered, g.registrationEnd) == ("2025-10-23", "2026-09-01")
    assert [o.name for o in g.owners] == ["438 52 ST OWNERS CORP"]


def test_live_multi_building_lot_anchor_d_spellings_as_recorded(live):
    client, graph, rg = live
    r = registered_owners(client, graph, rg, "224 54 Street, Brooklyn")
    assert [b.bin for b in r.buildings] == ["3324448", "3324450", "3324451"]
    assert [b.bin for b in r.buildings if b.addressed] == ["3324451"]
    regs = flat(r)
    assert set(regs) == {302437, 344220, 331116}
    names = {rid: [o.name for o in g.owners] for rid, g in regs.items()}
    assert names == {302437: ["HP SUNSET PARK I HDFC INC."], 344220: ["HP SUNSET PARK I HDFC INC."],
                     331116: ["HP SUNSET PARK I HDFC INC"]}


def test_live_registration_that_ended_before_the_snapshot(live):
    client, graph, rg = live
    r = registered_owners(client, graph, rg, "234 54 Street, Brooklyn")
    assert r.resolution.bbl == "3008210019"
    g = flat(r)[306882]
    assert (g.lastRegistered, g.registrationEnd) == ("2020-08-31", "2021-09-01")
    assert "registration_period" in codes(r)


def test_live_lot_with_no_hpd_building_says_so_and_infers_no_owner(live):
    client, graph, rg = live
    r = registered_owners(client, graph, rg, "70 Broad Street, Manhattan")
    assert r.buildings == () and P.CAVEAT_NO_BUILDING in r.caveats and R.CAVEAT_NOT_TITLE not in r.caveats


def test_live_joint_owner_entities_are_all_listed(live):
    _, _, rg = live
    r = build_registrations(answer(bbl="1020450057", bin="1060822"), rg)
    assert [o.name for o in flat(r)[121720].owners] == ["HP PLAZA LLC", "HP PLAZA LP"]


def test_live_two_registrations_one_has_no_owner_and_no_last_date(live):
    _, _, rg = live
    r = build_registrations(answer(bbl="5005760049", bin="5014747"), rg)
    regs = flat(r)
    assert set(regs) >= {11009, 11065}
    assert regs[11009].lastRegistered is None and regs[11009].owners == ()
    assert regs[11065].owners[0].contactType == "IndividualOwner"
    assert "no_owner_contact" in codes(r)
