import pytest
from neo4j import Query
from test_profile import LOT, answer
from test_registration import FakeRG, owner, row

from watchline.deeds import deeds as D
from watchline.deeds.deeds import build_comparison
from watchline.deeds.names import address_agreement, n1, n2, name_agreement
from watchline.profile import profile as P


class FakeDG:
    def __init__(self, rows=()):
        self._deed_rows = list(rows)

    def deeds(self, bbl): return self._deed_rows


def drow(doc="D1", rec="2025-04-02", amount=0, other=0, name="ACME LLC", addr="1 MAIN ST", l2=None, zip_="10001", doc_date="2025-03-14"):
    return dict(documentId=doc, docType="DEED", docDate=doc_date, recordedDate=rec, amount=amount, otherLots=other,
                name=name, mailingAddress=addr, addressLine2=l2, zip=zip_)


def owner_row(name="ACME LLC", addr="1 MAIN ST", zip_="10001", **kw):
    return {**owner(name=name, **kw), "mailingAddress": addr, "addressLine2": None, "zip": zip_}


def run(deed_rows, owners=(), rows=None, **kw):
    return build_comparison(answer(**kw), FakeRG(rows=[row()] if rows is None else rows, owners=list(owners)), FakeDG(deed_rows))


def codes(c):
    return {x.code for x in c.caveats}


# ---- the comparison rules --------------------------------------------------------------------------------------

@pytest.mark.parametrize("a, b, expected", [
    ("5413 PLAZA LLC", "5413  plaza llc ", ("exact_normalized", "N1")),
    ("HP PLAZA LLC.", "HP PLAZA LLC", ("normalization_match", "N2")),
    ("SMITH, JOHN", "SMITH JOHN", ("normalization_match", "N2")),
    ("K S TURNPIKE LLC", "KS Turnpike LLC", ("different", None)),       # anchor G: spaces are never removed
    ("AADVA REALTY LLC", "KS Turnpike LLC", ("different", None)),
    (None, "ACME", ("not_comparable", None)),
    ("ACME", "  ", ("not_comparable", None)),
])
def test_name_agreement(a, b, expected):
    assert name_agreement(a, b) == expected


def test_n1_and_n2():
    assert n1("  a   b ") == "A B" and n2("A.B, C") == "AB C"


@pytest.mark.parametrize("args, expected", [
    (("746 61ST STREET", "11220", "746  61st street", "11220-1234"), "same"),
    (("746 61ST STREET", "11220", "746 61ST ST", "11220"), "differs"),          # abbreviations are differences
    (("14 SINCLAIR DR", "11024", "209-19 33RD ROAD", "11361"), "differs"),
    (("14 SINCLAIR DR", "11024", "14 SINCLAIR DR", "11361"), "differs"),
    ((None, "11024", "14 SINCLAIR DR", "11024"), "absent"),
    (("14 SINCLAIR DR", None, "14 SINCLAIR DR", "11024"), "absent"),
])
def test_address_agreement(args, expected):
    assert address_agreement(*args) == expected


# ---- resolution short-circuits ---------------------------------------------------------------------------------

def test_unresolved_reads_no_deeds():
    class Boom:
        def deeds(self, bbl): raise AssertionError("must not read deeds for an unresolved address")
    c = build_comparison(answer(outcome=P.Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("A", "B")), FakeRG(), Boom())
    assert c.lot is None and c.deeds == () and P.CAVEAT_AMBIGUOUS in c.caveats


def test_lot_not_in_graph():
    c = build_comparison(answer(in_graph=False), FakeRG(), FakeDG())
    assert c.lot is None and P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001") in c.caveats


# ---- content ---------------------------------------------------------------------------------------------------

def test_exact_agreement_anchor_a_shape():
    c = run([drow()], [owner_row()])
    (d,) = c.deeds
    assert (d.documentId, d.recordedDate, d.docDate, d.amount) == ("D1", "2025-04-02", "2025-03-14", 0)
    (p,) = c.pairs
    assert (p.nameOutcome, p.nameRule, p.addressOutcome) == ("exact_normalized", "N1", "same")
    assert {"name_match_not_identity", "most_recent_by_recorded", "snapshots_differ", "deed_not_sale",
            "shared_address_not_evidence"} <= codes(c)
    assert D.ACRIS in c.sources


def test_name_and_address_are_separate_fields():
    c = run([drow(name="ACME LLC", addr="9 OTHER ST")], [owner_row()])
    (p,) = c.pairs
    assert p.nameOutcome == "exact_normalized" and p.addressOutcome == "differs"
    assert "shared_address_not_evidence" not in codes(c)


def test_two_grantees_one_owner_anchor_g_shape():
    rows = [drow(name="AADVA REALTY LLC", addr="14 SINCLAIR DR", zip_="11024", amount=4000000),
            drow(name="K S TURNPIKE LLC", addr="14 SINCLAIR DR", zip_="11024", amount=4000000)]
    c = run(rows, [owner_row(name="KS Turnpike LLC", addr="209-19 33RD ROAD", zip_="11361")])
    assert len(c.deeds) == 1 and [g.name for g in c.deeds[0].grantees] == ["AADVA REALTY LLC", "K S TURNPIKE LLC"]
    assert [p.nameOutcome for p in c.pairs] == ["different", "different"]
    assert "deed_not_sale" not in codes(c)


def test_tied_deeds_are_all_returned_and_none_chosen():
    c = run([drow("D1"), drow("D2", name="OTHER LLC")], [owner_row()])
    assert [d.documentId for d in c.deeds] == ["D1", "D2"] and "tied_deeds" in codes(c)


def test_multi_lot_deed_is_flagged():
    assert "multi_lot_deed" in codes(run([drow(other=3)], [owner_row()]))
    assert "multi_lot_deed" not in codes(run([drow(other=0)], [owner_row()]))


def test_exact_duplicate_grantee_rows_are_one_party():
    c = run([drow(), drow()], [owner_row()])
    assert len(c.deeds[0].grantees) == 1


def test_missing_doc_date_stays_absent():
    assert run([drow(doc_date=None)], [owner_row()]).deeds[0].docDate is None


def test_deed_without_grantee_is_kept_and_said():
    c = run([drow(name=None, addr=None, zip_=None)], [owner_row()])
    assert c.deeds[0].grantees == () and c.pairs == () and "deed_without_grantee" in codes(c)
    assert "name_match_not_identity" not in codes(c)


def test_no_deed_says_so_and_still_lists_owners():
    c = run([], [owner_row()])
    assert c.deeds == () and "no_deed_found" in codes(c) and len(c.owners) == 1
    assert "most_recent_by_recorded" not in codes(c)


def test_no_owner_means_no_pairs_and_none_inferred():
    c = run([drow()], [])
    assert c.pairs == () and "no_owner_contact" in codes(c)


def test_owners_repeated_across_buildings_are_compared_once():
    rows = [row("1", 100), row("2", 200)]
    c = run([drow()], [owner_row(rid=100), owner_row(rid=200)], rows=rows)
    assert len(c.owners) == 1 and len(c.pairs) == 1


def test_lot_with_no_hpd_building_still_lists_deeds():
    rg = FakeRG(lot={**LOT, "hpdRegistered": False}, rows=[])
    c = build_comparison(answer(), rg, FakeDG([drow()]))
    assert len(c.deeds) == 1 and c.owners == () and P.CAVEAT_NO_BUILDING in c.caveats


def test_registration_period_and_roles_caveats_are_not_carried():
    assert not {"registration_period", "owner_not_other_roles"} & codes(run([drow()], [owner_row()]))


def test_truncation_is_stated(monkeypatch):
    monkeypatch.setattr(D, "MAX_ROWS", 1)
    assert P.CAVEAT_TRUNCATED in run([drow()], [owner_row()]).caveats


def test_deed_query_is_read_routed_and_timed_out():
    seen = []

    class Result:
        records = []

    class Drv:
        def execute_query(self, q, params=None, **kw):
            seen.append((q, params, kw))
            return Result()

    D.Neo4jDeedGraph(Drv(), "watchline").deeds("1")
    ((q, params, kw),) = seen
    assert isinstance(q, Query) and q.timeout == P.TIMEOUT_S and kw["routing_"].value == "r"
    assert "DEED, TS" in params["types"] and "DEED COR" not in params["types"]


def test_deed_dates_from_the_driver_become_iso_strings():
    from neo4j.time import Date

    class Rec:
        def data(self):
            return drow(rec=Date(2025, 4, 2), doc_date=Date(2025, 3, 14)) | {"documentId": "D1"}

    class Result:
        records = [Rec()]

    class Drv:
        def execute_query(self, q, params=None, **kw): return Result()

    (row_,) = D.Neo4jDeedGraph(Drv(), "watchline").deeds("1")
    assert (row_["recordedDate"], row_["docDate"]) == ("2025-04-02", "2025-03-14")
