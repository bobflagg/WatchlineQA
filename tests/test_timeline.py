"""Q12.1 deed timeline: section function, tool view and contract wiring. No model, no graph."""
import pytest
from neo4j import Query
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import answer
from test_registration import FakeRG

from watchline.agent import tools as T
from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact, assemble, ungrounded_numbers
from watchline.deeds import timeline as TL
from watchline.deeds.timeline import build_timeline
from watchline.profile import profile as P


class FakeTG(FakeRG):
    def __init__(self, rows=(), counts=None, **kw):
        super().__init__(**kw)
        self._t = list(rows)
        self._c = counts if counts is not None else self._counts_of(self._t)
        self.asked = []

    @staticmethod
    def _counts_of(rows):
        g: dict = {}
        for r in rows:
            k = (r["docType"], r["amount"] == 0)
            g[k] = g.get(k, 0) + 1
        return [dict(docType=t, zero=z, n=n) for (t, z), n in sorted(g.items())]

    def timeline(self, bbl, since, until):
        self.asked.append((bbl, since, until))
        return self._t

    def deed_counts(self, bbl, since, until): return self._c


def trow(doc="D1", rec="2025-04-02", amount=0, typ="DEED", other=0, grantors=("A SELLER",), grantees=("A BUYER",), **kw):
    return dict(documentId=doc, docType=typ, docDate="2025-03-14", recordedDate=rec, amount=amount, otherLots=other,
                grantors=list(grantors), grantorRows=len(grantors), grantees=list(grantees), granteeRows=len(grantees), **kw)


def run(rows, **kw):
    return build_timeline(answer(), FakeTG(rows), **kw)


def codes(t):
    return {c.code for c in t.caveats}


# ---- counts ---------------------------------------------------------------------------------------------------------

def test_counts_separate_deeds_not_sales_and_zero_amounts():
    t = run([trow("D1", amount=5000000), trow("D2", amount=0), trow("D3", typ="CORRD", amount=10), trow("D4", typ="DEEDO", amount=0)])
    c = t.counts
    assert (c.deeds, c.notSale, c.amountZero) == (4, 3, 2)     # D3 is a correction deed with an amount: not a sale, not a zero
    assert dict(c.byType) == {"CORRD": 1, "DEED": 2, "DEEDO": 1}
    assert {"deed_not_sale", "deed_correction_type", "timeline_by_recorded", "party_names_as_recorded"} <= codes(t)


def test_sale_amount_only_has_no_not_sale_caveat():
    t = run([trow(amount=1000)])
    assert t.counts.notSale == 0 and "deed_not_sale" not in codes(t) and not t.deeds[0].notSale


def test_counts_cover_the_period_not_just_the_listed_deeds():
    rows = [trow(f"D{i}") for i in range(3)]
    t = build_timeline(answer(), FakeTG(rows, counts=[dict(docType="DEED", zero=True, n=120)]))
    assert t.counts.deeds == 120 and len(t.deeds) == 3 and "truncated" in codes(t)


# ---- other lots, period, absence ------------------------------------------------------------------------------------

def test_multi_lot_deed_is_one_deed_with_other_lots():
    t = run([trow("BIG", other=1075)])
    assert t.deeds[0].otherLots == 1075 and t.counts.deeds == 1 and "multi_lot_deed" in codes(t)


def test_period_is_passed_to_the_graph_and_flagged():
    tg = FakeTG([trow()])
    t = build_timeline(answer(), tg, since="2020-01-01", until="2025-12-31")
    assert tg.asked == [("1000010001", "2020-01-01", "2025-12-31")] and "period_bounds" in codes(t)
    assert (t.since, t.until) == ("2020-01-01", "2025-12-31")


def test_no_deed_says_so_and_still_reports_zero_counts():
    t = build_timeline(answer(), FakeTG([], counts=[]))
    assert t.deeds == () and t.counts.deeds == 0 and "no_deed_found" in codes(t) and "timeline_by_recorded" not in codes(t)


@pytest.mark.parametrize("kw, expected", [
    (dict(outcome=P.Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("MAIN ST", "MAIN AVE")), P.CAVEAT_AMBIGUOUS),
    (dict(outcome=P.Match.UNAVAILABLE, bbl=None, in_graph=None), P.CAVEAT_UNAVAILABLE),
    (dict(in_graph=False), P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001")),
])
def test_unresolved_reads_nothing(kw, expected):
    tg = FakeTG([trow()])
    t = build_timeline(answer(**kw), tg)
    assert t.lot is None and t.deeds == () and t.counts is None and expected in t.caveats and tg.asked == []


# ---- the real graph class: parameterized, limited, timed out ---------------------------------------------------------

def test_neo4j_timeline_graph_reads_are_parameterized_and_limited():
    seen = []

    class Rec:
        def __init__(self, d): self._d = d
        def data(self): return self._d

    class Res:
        records = [Rec(dict(documentId="D1", docType="DEED", docDate=None, recordedDate="2020-01-09", amount=0))]

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params, kw))
            return Res()

    g = TL.Neo4jTimelineGraph(Drv(), "watchline")
    (row,) = g.timeline("2030370098", "2000-01-01", None)
    assert row["recordedDate"] == "2020-01-09"
    g.deed_counts("2030370098", None, None)
    for q, params, _ in seen:
        assert isinstance(q, Query) and q.timeout and "$bbl" in q.text and "2030370098" not in q.text
        assert "$limit" in q.text and params["bbl"] == "2030370098" and "DEED" in params["types"]
    assert seen[0][1]["since"] == "2000-01-01" and seen[0][1]["limit"] == TL.MAX_DEEDS and seen[0][1]["names"] == TL.MAX_NAMES


# ---- the tool view and the answer contract ---------------------------------------------------------------------------

def tool(rows=(), **kw):
    return T.make_deed_timeline_tool(FakeClient(resolved()), FakeGraph(), FakeTG(rows, **kw))


def test_tool_name_args_and_description_for_the_model():
    t = tool()
    text = " ".join(t.description.split())
    assert t.name == "deed_timeline" and set(t.args) == {"address", "borough", "zip_code", "since", "until"}
    assert "not a sale" in text and "Never add counts" in text and "deed_vs_owner" in text


def test_tool_output_shape_has_no_sale_or_total_keys():
    out = tool([trow("D1", amount=0), trow("D2", amount=5, grantors=("X", "Y"))]).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "ok" and [d["documentId"] for d in out["timeline"]] == ["D1", "D2"]
    assert out["timeline"][0]["notSale"] is True and out["timeline"][1]["notSale"] is False
    assert out["timeline_counts"]["deeds"] == 2 and out["timeline_counts"]["notSale"] == 1
    assert not {"sale", "price", "total", "score", "owner"} & (set(out["timeline_counts"]) | set(out["timeline"][0]))


def test_tool_flags_capped_party_names():
    row = trow("BIG", grantees=("A", "B"))
    row["granteeRows"] = 14
    out = tool([row]).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert "party_names_capped" in {c["code"] for c in out["caveats"]}


def test_tool_statuses_are_answers_not_exceptions():
    out = T.make_deed_timeline_tool(FakeClient(error=RuntimeError("boom")), FakeGraph(), FakeTG()).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "error" and "RuntimeError" in out["message"] and out["sources"] == []


def test_assemble_points_at_timeline_and_counts_and_carries_caveats():
    out = tool([trow("D1", amount=0), trow("D2", amount=900)]).invoke({"address": "1 Main St", "borough": "Manhattan"})
    m = ModelAnswer(kind="timeline", summary="Two deeds are recorded; one is not a sale.", facts=[
        ModelFact(statement="Two deeds are recorded.", evidence=[EvidenceRef(section="timeline_counts")]),
        ModelFact(statement="Deed D1 was recorded 2025-04-02.", evidence=[EvidenceRef(section="timeline")])])
    a = assemble(m, [out])
    assert not any(f.unresolved for f in a.facts) and a.facts[0].evidence[0].data["deeds"] == 2
    assert {"deed_not_sale", "timeline_by_recorded"} <= a.caveat_codes


def test_summing_deed_counts_is_an_ungrounded_number():
    out = tool([trow("D1", amount=0), trow("D2", amount=900), trow("D3", amount=0)]).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert ungrounded_numbers("3 deeds, 2 not sales", [out]) == []
    assert ungrounded_numbers("5 deeds in total", [out]) == ["5"]
