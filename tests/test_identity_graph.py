"""Identity checkpoint, step 2: parties and candidate links from graph rows. Fake rows for the logic; live (no model) for the demo names."""
import os

import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase, Query

from watchline.identity import graph as G
from watchline.identity.checkpoint import Decision, build_checkpoint
from watchline.identity.graph import build_inputs

load_dotenv()


class FakeIG:
    """Landlord records, identity pairs, covered lots, name and address edges, and masks, as plain rows."""
    def __init__(self, records, identity=(), lots=(), edges=(), masks=()):
        self._r = {r["nodeId"]: r for r in records}
        self._id, self._lots, self._edges, self._masks = list(identity), list(lots), list(edges), list(masks)
        self.calls = []

    def records_named(self, name):
        self.calls.append("records_named")
        return [r for r in self._r.values() if r["name"] == name]

    def records(self, ids): return [self._r[i] for i in sorted(ids) if i in self._r]

    def identity_pairs(self, ids):
        both = self._id + [(b, a) for a, b in self._id]
        return [dict(nodeId=a, peerId=b) for a, b in sorted(set(both)) if a in ids]

    def lots(self, ids): return [r for r in self._lots if r["nodeId"] in ids]

    def lead_edges(self, ids):
        out = []
        for e in self._edges:
            for a, b in ((e["fromId"], e["toId"]), (e["toId"], e["fromId"])):
                if a in ids and b not in ids:
                    out.append(dict(e, fromId=a, toId=b))
        return out

    def masks(self, streets): return [m for m in self._masks if m["address"] in streets]


def rec(i, name, *addrs): return dict(nodeId=i, name=name, businessAddresses=list(addrs))
def lot(i, bbl, units): return dict(nodeId=i, bbl=bbl, unitsRes=units)
def edge(a, b, kind="ADDRESS", w=5.4): return dict(fromId=a, toId=b, type=f"CONNECTED_BY_{kind}", weight=w)


ADDR = "4058 BRONX BOULEVARD 1B, Bronx, NY 10466"
# Two records of one name joined by identity (3 + 2 lots), plus a similarly spelled record with one lot, linked by address only.
BASE = dict(
    records=[rec(1, "ACME OWNER", ADDR), rec(2, "ACME OWNER", "1 OTHER ST, Bronx, NY 10466"), rec(3, "ACME OWNR", ADDR)],
    identity=[(1, 2)],
    lots=[lot(1, "2000000001", 3), lot(1, "2000000002", 3), lot(2, "2000000002", 3), lot(2, "2000000003", None), lot(3, "2030370098", 3)],
    edges=[edge(1, 3), edge(2, 3)])


def test_identity_joined_records_are_one_party_and_a_lead_edge_is_one_link():
    i = build_inputs(FakeIG(**BASE), "ACME OWNER")
    assert i.status == "ok" and i.anchor.key == "ACME OWNER" and i.anchor.records == 2
    assert [x.bbl for x in i.anchor.lots] == ["2000000001", "2000000002", "2000000003"]       # a lot covered twice is one lot
    (ln,) = i.links
    assert ln.linkId == "ACME OWNER|ACME OWNR|address" and ln.b.records == 1 and [x.bbl for x in ln.b.lots] == ["2030370098"]
    (e,) = ln.evidence
    assert e.kind == "shared_address" and not e.setAside and ADDR in e.text and "2 links" in e.text


def test_the_demo_effect_on_fake_rows():
    i = build_inputs(FakeIG(**BASE), "ACME OWNER")
    cp = build_checkpoint(i.anchor, i.links, [Decision(i.links[0].linkId, "accept", "researcher", "2026-12-01")])
    assert (cp.effect.as_held.lots, cp.effect.as_held.units, cp.effect.as_held.unitsMissing) == (3, 6, 1)
    assert (cp.effect.as_decided.lots, cp.effect.as_decided.units) == (4, 9)


def test_unknown_name_is_not_found_and_reads_nothing_more():
    ig = FakeIG(**BASE)
    i = build_inputs(ig, "NOBODY")
    assert i.status == "not_found" and i.anchor is None and i.links == ()


def test_a_name_in_two_identity_groups_is_ambiguous_and_nothing_is_chosen():
    ig = FakeIG(records=[rec(1, "SAME NAME"), rec(2, "SAME NAME")], lots=[lot(1, "2000000001", 3), lot(2, "3000000001", 4), lot(2, "3000000002", 4)])
    i = build_inputs(ig, "SAME NAME")
    assert i.status == "ambiguous_name" and i.anchor is None and i.links == () and i.candidates == (("SAME NAME", 1), ("SAME NAME", 2))


def test_masked_and_mail_drop_addresses_are_set_aside_with_the_reason():
    masks = [dict(list="maildrop", address="4058 BRONX BOULEVARD 1B", degree=None, kind="registered_agent", zip5="10466", status="unreviewed")]
    i = build_inputs(FakeIG(**BASE, masks=masks), "ACME OWNER")
    (e,) = i.links[0].evidence
    assert e.setAside and e.reason == "on the mail-drop list (registered_agent, unreviewed)"
    cp = build_checkpoint(i.anchor, i.links)
    assert cp.links[0].state == "unsupported" and "evidence_set_aside" in {c.code for c in cp.caveats}


def test_a_mail_drop_street_in_a_different_zip_is_not_a_match():
    masks = [dict(list="maildrop", address="4058 BRONX BOULEVARD 1B", degree=None, kind="registered_agent", zip5="12207", status="unreviewed")]
    (e,) = build_inputs(FakeIG(**BASE, masks=masks), "ACME OWNER").links[0].evidence
    assert not e.setAside


def test_network_and_portfolio_masks_are_set_aside_with_their_degree():
    for lst, expected in (("network", "masked by the network method (degree 53)"), ("portfolio", "masked by the portfolio method (degree 53)")):
        masks = [dict(list=lst, address="4058 BRONX BOULEVARD 1B", degree=53, kind=None, zip5=None, status=None)]
        (e,) = build_inputs(FakeIG(**BASE, masks=masks), "ACME OWNER").links[0].evidence
        assert e.reason == expected


def test_when_the_shared_string_is_not_identified_the_evidence_says_so():
    base = dict(BASE, records=[rec(1, "ACME OWNER", "1 A ST, Bronx, NY 10466"), rec(2, "ACME OWNER"), rec(3, "ACME OWNR", "9 B ST, Bronx, NY 10451")])
    (e,) = build_inputs(FakeIG(**base), "ACME OWNER").links[0].evidence
    assert "which string is not identified" in e.text and "9 B ST" in e.text


def test_name_links_carry_the_named_rule_only_when_the_names_compare_equal():
    base = dict(BASE, records=[rec(1, "ACME OWNER, LLC"), rec(2, "ACME OWNER, LLC"), rec(3, "ACME OWNER LLC")], edges=[edge(1, 3, "NAME", 1.0)])
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER, LLC").links
    assert ln.kind == "name" and ln.rule == "N2" and ln.evidence[0].kind == "name_similarity"
    base["records"][2] = rec(3, "OTHER NAME")
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER, LLC").links
    assert ln.rule is None


def test_address_and_name_edges_to_one_party_are_two_links_judged_separately():
    base = dict(BASE, edges=[edge(1, 3), edge(1, 3, "NAME", 1.0)])
    links = build_inputs(FakeIG(**base), "ACME OWNER").links
    assert sorted(x.linkId for x in links) == ["ACME OWNER|ACME OWNR|address", "ACME OWNER|ACME OWNR|name"]


def test_two_candidate_groups_with_one_name_are_told_apart_by_a_lot_not_an_id():
    base = dict(records=[rec(1, "ACME OWNER", ADDR), rec(2, "SAME NAME", ADDR), rec(3, "SAME NAME", ADDR)], identity=[],
                lots=[lot(1, "2000000001", 3), lot(2, "3000000001", 3), lot(3, "3000000002", 3)], edges=[edge(1, 2), edge(1, 3)])
    ids = sorted(x.linkId for x in build_inputs(FakeIG(**base), "ACME OWNER").links)
    assert ids == ["ACME OWNER|SAME NAME [lot 3000000002]|address", "ACME OWNER|SAME NAME|address"]


def test_a_result_is_deterministic():
    assert build_inputs(FakeIG(**BASE), "ACME OWNER") == build_inputs(FakeIG(**BASE), "ACME OWNER")


def test_street_and_zip_parsing_and_masks_as_spelled():
    assert G._street_zip("4058 BRONX BOULEVARD, 1B, Bronx, NY 10466") == ("4058 BRONX BOULEVARD", "10466", "4058 BRONX BOULEVARD 1B")
    assert G._street_zip("418 BROADWAY, Albany, NY 12207-1234")[:2] == ("418 BROADWAY", "12207")


def test_neo4j_identity_graph_reads_are_parameterized_limited_and_timed_out():
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params))
            return Res()

    g = G.Neo4jIdentityGraph(Drv(), "watchline")
    g.records_named("YONATAN BAHUMI")
    g.records([1])
    g.identity_pairs([1])
    g.lots([1])
    g.lead_edges([1])
    g.masks(["X"])
    assert len(seen) == 6
    for q, params in seen:
        assert isinstance(q, Query) and q.timeout and "YONATAN" not in q.text and params
    assert all("$limit" in q.text for q, _ in seen[:5]) and "nodeId" not in "".join(str(v) for _, p in seen for v in p.values() if isinstance(v, str))


# ---- live (no model): the demo names, looked up by name ----------------------------------------------------------------

@pytest.fixture(scope="module")
def live_graph():
    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))
    if not (uri and user and pw):
        pytest.skip("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.skip(f"Neo4j not reachable: {exc}")
    yield G.Neo4jIdentityGraph(driver, os.environ["NEO4J_DATABASE"])
    driver.close()


def test_live_bahumi_and_the_badhumi_checkpoint(live_graph):
    """Probed 2026-11-25: BAHUMI is 6 records joined by identity, 55 lots, 176 units; BADHUMI is 1 record, 1 lot, 3 units, linked by address."""
    i = build_inputs(live_graph, "YONATAN BAHUMI")
    assert i.status == "ok" and (i.anchor.key, i.anchor.records, len(i.anchor.lots)) == ("YONATAN BAHUMI", 6, 55)
    (ln,) = [x for x in i.links if "BADHUMI" in x.linkId]
    assert ln.linkId == "YONATAN BAHUMI|YONATAN BADHUMI|address" and [x.bbl for x in ln.b.lots] == ["2030370098"]
    assert [e.setAside for e in ln.evidence] == [False]
    cp = build_checkpoint(i.anchor, i.links, [Decision(ln.linkId, "accept", "researcher", "2026-12-01")])
    assert (cp.effect.as_held.lots, cp.effect.as_held.units) == (55, 176)
    assert (cp.effect.as_decided.lots, cp.effect.as_decided.units) == (56, 179) and cp.effect.added_lots == ("2030370098",)


def test_live_badhumi_from_the_other_side_and_unknown_name(live_graph):
    i = build_inputs(live_graph, "YONATAN BADHUMI")
    assert (i.anchor.records, len(i.anchor.lots)) == (1, 1) and any(x.b.key == "YONATAN BAHUMI" and len(x.b.lots) == 55 for x in i.links)
    assert build_inputs(live_graph, "NO SUCH LANDLORD NAME").status == "not_found"


def test_live_berkovics_identity_group_spans_several_names(live_graph):
    """Probed 2026-11-25: the identity group around MOSES BERKOVICS holds 8 records under three recorded names (48 lots, 1628 units)."""
    i = build_inputs(live_graph, "MOSES BERKOVICS")
    assert i.status == "ok" and i.anchor.key == "ALBERT LABOZ / AMNON SHALHOV / MOSES BERKOVICS"
    assert (i.anchor.records, len(i.anchor.lots), sum(x.unitsRes or 0 for x in i.anchor.lots)) == (8, 48, 1628)
    assert not any(e.setAside for ln in i.links for e in ln.evidence)
