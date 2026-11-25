"""Identity checkpoint, step 2: parties and candidate links from graph rows. Fake rows for the logic; live (no model) for the demo names."""

from dotenv import load_dotenv
from neo4j import Query

from watchline.identity import graph as G
from watchline.identity.checkpoint import Decision, build_checkpoint
from watchline.identity.graph import build_inputs

load_dotenv()


class FakeIG:
    """Landlord records, identity pairs, covered lots, name and address edges, and masks, as plain rows."""
    def __init__(self, records, identity=(), lots=(), edges=(), masks=(), registrations=()):
        self._r = {r["nodeId"]: r for r in records}
        self._id, self._lots, self._edges, self._masks = list(identity), list(lots), list(edges), list(masks)
        self._regs = list(registrations)
        self.reg_calls = []
        self.calls = []

    def landlords_covering(self, bbl):
        return sorted({self._r[x["nodeId"]]["name"] for x in self._lots if x["bbl"] == bbl and x["nodeId"] in self._r})

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

    def shared_registrations(self, bbls, names_a, names_b):
        self.reg_calls.append((bbls, names_a, names_b))
        return [r for r in self._regs if r["bbl"] in bbls and r["nameA"] in names_a and r["nameB"] in names_b]


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
    assert ln.linkId == "ACME OWNER|ACME OWNR" and ln.b.records == 1 and [x.bbl for x in ln.b.lots] == ["2030370098"]
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
    assert ln.kinds == ("name",) and ln.rule == "N2" and ln.evidence[0].kind == "name_similarity"
    base["records"][2] = rec(3, "OTHER NAME")
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER, LLC").links
    assert ln.rule is None


def test_address_and_name_edges_to_one_party_are_one_link_with_both_kinds_of_evidence():
    base = dict(BASE, edges=[edge(1, 3), edge(1, 3, "NAME", 1.0)])
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER").links
    assert ln.linkId == "ACME OWNER|ACME OWNR" and ln.kinds == ("address", "name")
    assert [e.kind for e in ln.evidence] == ["shared_address", "name_similarity"]


def test_two_candidate_groups_with_one_name_are_told_apart_by_a_lot_not_an_id():
    base = dict(records=[rec(1, "ACME OWNER", ADDR), rec(2, "SAME NAME", ADDR), rec(3, "SAME NAME", ADDR)], identity=[],
                lots=[lot(1, "2000000001", 3), lot(2, "3000000001", 3), lot(3, "3000000002", 3)], edges=[edge(1, 2), edge(1, 3)])
    ids = sorted(x.linkId for x in build_inputs(FakeIG(**base), "ACME OWNER").links)
    assert ids == ["ACME OWNER|SAME NAME", "ACME OWNER|SAME NAME [lot 3000000002]"]


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

def test_live_bahumi_and_the_badhumi_checkpoint(live_graph):
    """Probed 2026-11-25: BAHUMI is 6 records joined by identity, 55 lots, 176 units; BADHUMI is 1 record, 1 lot, 3 units, linked by address."""
    i = build_inputs(live_graph, "YONATAN BAHUMI")
    assert i.status == "ok" and (i.anchor.key, i.anchor.records, len(i.anchor.lots)) == ("YONATAN BAHUMI", 6, 55)
    (ln,) = [x for x in i.links if "BADHUMI" in x.linkId]                             # one link for the pair
    assert ln.linkId == "YONATAN BAHUMI|YONATAN BADHUMI" and [x.bbl for x in ln.b.lots] == ["2030370098"]
    assert ln.kinds == ("address", "contact")                                          # the address edge, and registration 205148 listing both names
    address, reg = ln.evidence
    assert address.kind == "shared_address" and not address.setAside
    assert reg.kind == "shared_contact" and "registration 205148" in reg.text and "YONATAN BADHUMI as HeadOfficer" in reg.text
    assert "YONATAN BAHUMI as Officer and Shareholder" in reg.text
    assert "No joining record other than a shared address was found." not in build_checkpoint(i.anchor, i.links).links[0].against
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


# ---- link ids stay unique, and a cut read is flagged ---------------------------------------------------------------------

def test_groups_with_one_name_and_one_first_lot_or_no_lot_still_get_distinct_link_ids():
    for lots in ([lot(2, "3000000001", 3), lot(3, "3000000001", 3)], []):
        base = dict(records=[rec(1, "ACME OWNER", ADDR), rec(2, "SAME NAME", ADDR), rec(3, "SAME NAME", ADDR)], identity=[],
                    lots=[lot(1, "2000000001", 3), *lots], edges=[edge(1, 2), edge(1, 3)])
        ids = sorted(x.linkId for x in build_inputs(FakeIG(**base), "ACME OWNER").links)
        assert len(ids) == 2 and len(set(ids)) == 2
        build_checkpoint(*(lambda i: (i.anchor, i.links))(build_inputs(FakeIG(**base), "ACME OWNER")))     # no duplicate-id error


def test_reads_cut_at_the_row_limit_are_flagged(monkeypatch):
    monkeypatch.setattr(G, "MAX_GROUPS", 3)
    many = [lot(1, f"20000000{i:02d}", 3) for i in range(5)]
    i = build_inputs(FakeIG(**dict(BASE, lots=many)), "ACME OWNER")
    assert "identity_party_cut" in {c.code for c in i.caveats}
    monkeypatch.setattr(G, "MAX_GROUPS", 1000)
    assert "identity_party_cut" not in {c.code for c in build_inputs(FakeIG(**BASE), "ACME OWNER").caveats}
    monkeypatch.setattr(G, "MAX_GROUPS", 1)
    assert "identity_party_cut" in {c.code for c in build_inputs(FakeIG(**dict(BASE, edges=[edge(1, 3)])), "ACME OWNER").caveats}   # edges, pairs


# ---- shared registrations: names listed together on one HPD registration -----------------------------------------------------

def reg(rid, bbl, name_a, role_a, name_b, role_b, address="2 B ST"):
    return dict(registrationId=rid, bbl=bbl, address=address, nameA=name_a, roleA=role_a, nameB=name_b, roleB=role_b)


REGS = [reg(205148, "2030370098", "ACME OWNER", "Officer", "ACME OWNR", "HeadOfficer"),
        reg(205148, "2030370098", "ACME OWNER", "Shareholder", "ACME OWNR", "HeadOfficer")]


def test_a_registration_listing_both_names_is_one_evidence_item_with_every_role_on_the_same_link():
    ig = FakeIG(**BASE, registrations=REGS)
    i = build_inputs(ig, "ACME OWNER")
    (ln,) = i.links                                                        # one link, one decision, per pair
    assert ln.linkId == "ACME OWNER|ACME OWNR" and ln.kinds == ("address", "contact")
    shared, registration = ln.evidence
    assert shared.kind == "shared_address" and registration.kind == "shared_contact"
    assert not registration.setAside and registration.source == G.SOURCE_REGISTRATIONS
    assert registration.text == "HPD registration 205148 of lot 2030370098 (2 B ST) lists ACME OWNER as Officer and Shareholder; ACME OWNR as HeadOfficer."
    assert "registration_names_as_recorded" in {c.code for c in i.caveats}
    bbls, names_a, names_b = ig.reg_calls[0]
    assert names_a == ["ACME OWNER"] and names_b == ["ACME OWNR"] and set(bbls) == {"2000000001", "2000000002", "2000000003", "2030370098"}


def test_no_shared_registration_means_address_evidence_only_and_no_caveat():
    i = build_inputs(FakeIG(**BASE), "ACME OWNER")
    assert [x.kinds for x in i.links] == [("address",)] and "registration_names_as_recorded" not in {c.code for c in i.caveats}


def test_a_party_found_only_by_a_registration_edge_is_not_discovered():
    ig = FakeIG(**dict(BASE, edges=[]), registrations=REGS)
    assert build_inputs(ig, "ACME OWNER").links == ()


def test_a_shared_registration_removes_the_claim_that_only_an_address_joins_the_parties():
    alone = build_checkpoint(*(lambda i: (i.anchor, i.links))(build_inputs(FakeIG(**BASE), "ACME OWNER")))
    assert "No joining record other than a shared address was found." in alone.links[0].against
    both = build_checkpoint(*(lambda i: (i.anchor, i.links))(build_inputs(FakeIG(**BASE, registrations=REGS), "ACME OWNER")))
    assert "No joining record other than a shared address was found." not in both.links[0].against
    assert "shared_registration_not_identity" in {c.code for c in both.caveats}


def test_one_decision_covers_the_pair_and_its_evidence_of_every_kind():
    i = build_inputs(FakeIG(**BASE, registrations=REGS), "ACME OWNER")
    accepted = build_checkpoint(i.anchor, i.links, [Decision("ACME OWNER|ACME OWNR", "accept", "researcher", "2026-12-01")])
    assert [(x.state, len(x.evidence)) for x in accepted.links] == [("accepted", 2)] and accepted.effect.as_decided.lots == 4
    rejected = build_checkpoint(i.anchor, i.links, [Decision("ACME OWNER|ACME OWNR", "reject", "researcher", "2026-12-01")])
    assert [x.state for x in rejected.links] == ["rejected"] and rejected.effect.as_decided.lots == 3


def test_the_pair_is_usable_when_the_address_is_set_aside_but_a_registration_lists_both_names():
    masks = [dict(list="maildrop", address="4058 BRONX BOULEVARD 1B", degree=None, kind="registered_agent", zip5="10466", status="unreviewed")]
    i = build_inputs(FakeIG(**BASE, masks=masks, registrations=REGS), "ACME OWNER")
    cp = build_checkpoint(i.anchor, i.links)
    assert cp.links[0].state == "awaiting" and [e.setAside for e in cp.links[0].evidence] == [True, False]


def test_many_registrations_are_capped_with_a_count_of_the_rest(monkeypatch):
    monkeypatch.setattr(G, "MAX_REGISTRATION_ITEMS", 2)
    rows = [reg(100 + n, "2030370098", "ACME OWNER", "Officer", "ACME OWNR", "HeadOfficer") for n in range(5)]
    (ln,) = build_inputs(FakeIG(**BASE, registrations=rows), "ACME OWNER").links
    registrations = [e for e in ln.evidence if e.kind == "shared_contact"]
    assert len(registrations) == 3 and registrations[-1].text == "3 more registrations also list both names."


def test_a_registration_read_cut_at_its_row_limit_is_flagged(monkeypatch):
    monkeypatch.setattr(G, "MAX_REGISTRATION_ROWS", 1)
    assert "identity_party_cut" in {c.code for c in build_inputs(FakeIG(**BASE, registrations=REGS[:1]), "ACME OWNER").caveats}


def test_the_registration_read_is_parameterized_limited_and_timed_out():
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params))
            return Res()

    G.Neo4jIdentityGraph(Drv(), "watchline").shared_registrations(["2030370098"], ["YONATAN BAHUMI"], ["YONATAN BADHUMI"])
    ((q, params),) = seen
    assert q.timeout and "$limit" in q.text and "YONATAN" not in q.text and "2030370098" not in q.text
    assert params["bbls"] == ["2030370098"] and params["namesA"] == ["YONATAN BAHUMI"] and params["limit"] == G.MAX_REGISTRATION_ROWS


# ---- fixes from the code review of the identity changes (2026-11-25) -------------------------------------------------------------------

def test_a_name_on_both_sides_is_left_out_of_the_registration_read_and_the_query_needs_two_different_contacts():
    base = dict(BASE, records=[rec(1, "ACME OWNER", ADDR), rec(2, "SHARED NAME", ADDR), rec(3, "ACME OWNR", ADDR), rec(4, "SHARED NAME")], identity=[(1, 2), (3, 4)])
    ig = FakeIG(**base)
    build_inputs(ig, "ACME OWNER")
    ((_, names_a, names_b),) = ig.reg_calls
    assert names_a == ["ACME OWNER"] and names_b == ["ACME OWNR"]          # SHARED NAME is on both sides, so neither list has it
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append(q.text)
            return Res()

    G.Neo4jIdentityGraph(Drv(), "watchline").shared_registrations(["2030370098"], ["A"], ["B"])
    assert "cb <> ca" in seen[0]


def test_an_address_only_link_between_names_that_compare_equal_still_carries_the_rule():
    base = dict(BASE, records=[rec(1, "ACME OWNER, LLC", ADDR), rec(2, "ACME OWNER, LLC"), rec(3, "ACME OWNER LLC", ADDR)])
    i = build_inputs(FakeIG(**base), "ACME OWNER, LLC")
    (ln,) = i.links
    assert ln.kinds == ("address",) and ln.rule == "N2"
    cp = build_checkpoint(i.anchor, i.links)
    assert not any(x.startswith("The names differ") for x in cp.links[0].against) and "name_match_not_identity" in {c.code for c in cp.caveats}


def test_a_contact_with_no_recorded_role_is_shown_as_such_and_does_not_crash():
    rows = [dict(REGS[0], roleB=None), dict(REGS[0], roleA=None, roleB="HeadOfficer")]
    (ln,) = build_inputs(FakeIG(**BASE, registrations=rows), "ACME OWNER").links
    text = next(e.text for e in ln.evidence if e.kind == "shared_contact")
    assert text == ("HPD registration 205148 of lot 2030370098 (2 B ST) lists ACME OWNER as Officer and role not recorded; "
                    "ACME OWNR as HeadOfficer and role not recorded.")


def test_records_are_read_in_chunks_so_none_is_left_out(monkeypatch):
    monkeypatch.setattr(G, "RECORD_CHUNK", 2)
    sizes = []

    class Chunked(FakeIG):
        def records(self, ids):
            sizes.append(len(ids))
            return super().records(ids)

    i = build_inputs(Chunked(**BASE), "ACME OWNER")
    assert sizes and max(sizes) <= 2 and sum(sizes) >= 3
    assert i.anchor.key == "ACME OWNER" and [x.b.key for x in i.links] == ["ACME OWNR"]
    assert G._key({99}, {}) == "(record not read)"


def test_an_address_edge_to_a_record_with_no_address_is_still_a_lead_with_an_honest_line():
    base = dict(BASE, records=[rec(1, "ACME OWNER", ADDR), rec(2, "ACME OWNER"), dict(nodeId=3, name="ACME OWNR", businessAddresses=None)])
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER").links
    assert ln.kinds == ("address",) and "no business address is recorded on ACME OWNR" in ln.evidence[0].text


def test_one_registration_read_serves_every_party_and_each_party_gets_only_its_own_rows():
    base = dict(records=[rec(1, "ACME OWNER", ADDR), rec(2, "PARTY ONE", ADDR), rec(3, "PARTY TWO", ADDR)], identity=[],
                lots=[lot(1, "2000000001", 3), lot(2, "3000000001", 3), lot(3, "4000000001", 3)], edges=[edge(1, 2), edge(1, 3)],
                registrations=[reg(1, "3000000001", "ACME OWNER", "Officer", "PARTY ONE", "Agent"),
                               reg(2, "2000000001", "ACME OWNER", "Officer", "PARTY TWO", "Agent"),
                               reg(3, "9999999999", "ACME OWNER", "Officer", "PARTY TWO", "Agent")])    # a lot of neither party: not evidence
    ig = FakeIG(**base)
    links = {x.b.key: x for x in build_inputs(ig, "ACME OWNER").links}
    assert len(ig.reg_calls) == 1
    contact = lambda k: [e.text for e in links[k].evidence if e.kind == "shared_contact"]   # noqa: E731
    assert len(contact("PARTY ONE")) == 1 and "registration 1 " in contact("PARTY ONE")[0]
    assert len(contact("PARTY TWO")) == 1 and "registration 2 " in contact("PARTY TWO")[0]


def test_the_overflow_line_counts_registrations_not_items_and_says_when_only_lots_were_cut(monkeypatch):
    monkeypatch.setattr(G, "MAX_REGISTRATION_ITEMS", 2)
    many_lots = [reg(100, f"20300700{n:02d}", "ACME OWNER", "Officer", "ACME OWNR", "Agent") for n in range(5)]
    lots = BASE["lots"] + [lot(3, f"20300700{n:02d}", 3) for n in range(5)]
    (ln,) = build_inputs(FakeIG(**dict(BASE, lots=lots), registrations=many_lots), "ACME OWNER").links
    assert [e.text for e in ln.evidence if e.kind == "shared_contact"][-1] == "The registrations shown also cover 3 more lots where both names are listed."
    two = [reg(100 + n, "2030370098", "ACME OWNER", "Officer", "ACME OWNR", "Agent") for n in range(3)]
    (ln,) = build_inputs(FakeIG(**BASE, registrations=two), "ACME OWNER").links
    assert [e.text for e in ln.evidence if e.kind == "shared_contact"][-1] == "1 more registration also lists both names."


def test_addresses_that_differ_only_in_case_are_one_item_of_evidence():
    base = dict(BASE, records=[rec(1, "ACME OWNER", ADDR), rec(2, "ACME OWNER"), rec(3, "ACME OWNR", ADDR.replace("Bronx", "BRONX"), ADDR)])
    (ln,) = build_inputs(FakeIG(**base), "ACME OWNER").links
    assert [e.kind for e in ln.evidence] == ["shared_address"]
