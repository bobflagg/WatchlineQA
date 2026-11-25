"""Conditions: open violations (Q15) and litigation cases (Q28). Section functions, tool views and contract wiring. No graph, no model."""
import pytest
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import BUILDINGS, LOT, answer

from watchline.agent import tools as T
from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact, assemble, ungrounded_numbers
from watchline.conditions import conditions as C
from watchline.conditions.conditions import build_litigation, build_violations
from watchline.profile import profile as P


class FakeCG:
    def __init__(self, lot=LOT, buildings=BUILDINGS, groups=(), cases=(), counts=None, owners=()):
        self._lot, self._b, self._g, self._c, self._o = lot, list(buildings), list(groups), list(cases), list(owners)
        self._counts = counts

    def lot(self, bbl): return self._lot
    def buildings(self, bbl): return self._b
    def violation_groups(self, bbl): return self._g
    def cases(self, bbl): return self._c
    def owners(self, bbl): return self._o

    def case_counts(self, bbl):
        if self._counts is not None:
            return self._counts
        out: dict = {}
        for c in self._c:
            k = (c.get("caseType"), c.get("caseStatus"), c.get("harassmentFinding"))
            out[k] = out.get(k, 0) + 1
        return [dict(caseType=t, caseStatus=s, harassmentFinding=f, n=n) for (t, s, f), n in out.items()]


def g(bin_="1", cls="B", status="Open", n=1, oldest="2024-01-01"):
    return dict(bin=bin_, violationClass=cls, status=status, n=n, oldest=oldest)


def case(i=1, bin_="1", typ="Tenant Action", status="CLOSED", finding=None, resp="ACME LLC", keys=("ACME LLC",), opened="2023-05-15", **kw):
    return dict(bin=bin_, litigationId=i, caseType=typ, caseOpenDate=opened, caseStatus=status, openJudgement="NO", harassmentFinding=finding,
                findingDate=kw.get("findingDate"), penalty=kw.get("penalty"), respondent=resp, respondentKeys=list(keys) if keys is not None else None)


def codes(x):
    return {c.code for c in x.caveats}


# ---- Q15: violations ----------------------------------------------------------------------------------------------------------

def test_open_violations_by_class_oldest_open_and_the_rate_per_unit():
    lot = dict(LOT, unitsRes=32)
    rows = [g("1", "B", "Open", 2, "2023-03-25"), g("1", "C", "Open", 2, "2024-02-01"), g("1", "A", "Close", 1, "2019-01-01"), g("1", "B", "Close", 3, "2018-01-01")]
    v = build_violations(answer(), FakeCG(lot=lot, buildings=[BUILDINGS[0]], groups=rows))
    (b,) = v.buildings
    assert b.oldestOpen == "2023-03-25"                                   # closed violations never set the age of the open ones
    assert [(x.violationClass, x.status, x.n) for x in b.groups] == [("B", "Open", 2), ("C", "Open", 2), ("A", "Close", 1), ("B", "Close", 3)]
    assert (v.rate.open, v.rate.units, v.rate.perUnit) == (4, 32, 0.125)
    assert {"cited_not_fault", "open_at_snapshot", "lot_wide", "rate_lot_wide_units"} <= codes(v)


def test_the_pooled_rate_always_comes_with_the_rate_for_each_class():
    v = build_violations(answer(), FakeCG(lot=dict(LOT, unitsRes=10), groups=[g("1", "A", "Open", 3), g("1", "C", "Open", 2), g("2", "C", "Open", 1), g("1", "A", "Close", 9)]))
    assert v.rate.byClass == (("A", 3, 0.3), ("C", 3, 0.3)) and (v.rate.open, v.rate.perUnit) == (6, 0.6)
    assert "adds the open violations of every class" in next(c.text for c in v.caveats if c.code == "rate_lot_wide_units")


def test_more_buildings_than_can_be_read_flags_the_count_and_gives_no_rate():
    many = [dict(bin=str(i), address=f"{i} MAIN ST") for i in range(P.MAX_BUILDINGS)]
    v = build_violations(answer(), FakeCG(buildings=many, groups=[g("1", "A", "Open", 3)]))
    assert v.rate.open == 3 and v.rate.perUnit is None and all(p is None for _, _, p in v.rate.byClass)
    assert {"rate_incomplete", "truncated"} <= codes(v) and "rate_lot_wide_units" not in codes(v)
    assert "truncated" in codes(build_litigation(answer(), FakeCG(buildings=many, cases=[case()])))
    assert "truncated" in codes(build_litigation(answer(), FakeCG(buildings=many, cases=[])))


def test_case_counts_cut_at_the_group_limit_are_flagged(monkeypatch):
    monkeypatch.setattr(C, "MAX_GROUPS", 2)
    rows = [dict(caseType="A", caseStatus="CLOSED", harassmentFinding=None, n=1), dict(caseType="B", caseStatus="CLOSED", harassmentFinding=None, n=1)]
    assert "truncated" in codes(build_litigation(answer(), FakeCG(cases=[case()], counts=rows)))


def test_cases_are_read_with_undated_cases_last():
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append(q.text)
            return Res()

    C.Neo4jConditionsGraph(Drv(), "watchline").cases("2042920024")
    assert "ORDER BY noDate, caseOpenDate DESC" in seen[0]


def test_the_oldest_open_date_is_per_building_and_the_rate_pools_every_listed_building():
    v = build_violations(answer(), FakeCG(groups=[g("1", "A", "Open", 3, "2022-05-01"), g("2", "C", "Open", 1, "2019-02-02"), g("2", "C", "Close", 9, "2001-01-01")]))
    assert {b.bin: b.oldestOpen for b in v.buildings} == {"1": "2022-05-01", "2": "2019-02-02"}
    assert (v.rate.open, v.rate.units, v.rate.perUnit) == (4, 24, 0.167)


@pytest.mark.parametrize("units", [0, None])
def test_a_zero_or_missing_unit_count_gives_no_rate(units):
    v = build_violations(answer(), FakeCG(lot=dict(LOT, unitsRes=units), groups=[g()]))
    assert v.rate.perUnit is None and v.rate.open == 1 and "rate_unavailable" in codes(v) and "rate_lot_wide_units" not in codes(v)


def test_no_violations_is_not_a_clean_record_and_a_building_without_any_has_no_oldest_open():
    v = build_violations(answer(), FakeCG(groups=[]))
    assert "no_violations_recorded" in codes(v) and v.rate.open == 0 and all(b.oldestOpen is None and b.groups == () for b in v.buildings)


@pytest.mark.parametrize("kw, expected", [
    (dict(outcome=P.Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("MAIN ST", "MAIN AVE")), P.CAVEAT_AMBIGUOUS),
    (dict(in_graph=False), P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001")),
])
def test_unresolved_reads_nothing(kw, expected):
    v = build_violations(answer(**kw), FakeCG(groups=[g()]))
    assert v.lot is None and v.buildings == () and v.rate is None and expected in v.caveats


def test_a_lot_with_no_listed_building_says_so_and_has_no_rate():
    v = build_violations(answer(), FakeCG(buildings=[], groups=[g()]))
    assert v.buildings == () and v.rate is None and (P.CAVEAT_NO_BUILDING in v.caveats or P.CAVEAT_REGISTERED_NO_BUILDING in v.caveats)


# ---- Q28: litigation ----------------------------------------------------------------------------------------------------------

def test_only_after_inquest_and_after_trial_are_harassment_findings():
    cs = [case(1, finding="After Trial", findingDate="2016-07-25", penalty=5200), case(2, finding="After Inquest"),
          case(3, finding="No Harassment"), case(4, finding=None)]
    lit = build_litigation(answer(), FakeCG(cases=cs))
    assert [c.isHarassmentFinding for c in lit.cases] == [True, True, False, False]
    assert dict(lit.counts.byFinding) == {"After Trial": 1, "After Inquest": 1, "No Harassment": 1, "none recorded": 1}
    assert (lit.cases[0].findingDate, lit.cases[0].penalty) == ("2016-07-25", 5200)
    assert {"cited_not_fault", "case_not_finding", "harassment_finding_definition", "respondent_role_not_recorded"} <= codes(lit)


def test_counts_cover_every_case_by_type_and_by_status_and_are_never_combined_across_them():
    cs = [case(1, typ="Heat and Hot Water"), case(2, typ="Tenant Action", status="PENDING")]
    lit = build_litigation(answer(), FakeCG(cases=cs))
    assert lit.counts.cases == 2 and dict(lit.counts.byType) == {"Heat and Hot Water": 1, "Tenant Action": 1}
    assert dict(lit.counts.byStatus) == {"CLOSED": 1, "PENDING": 1}


def test_a_respondent_that_matches_an_owner_name_is_a_lead_and_others_are_not():
    owners = [dict(name="ACME LLC", registrationId=1)]
    lit = build_litigation(answer(), FakeCG(owners=owners, cases=[
        case(1, resp="ACME LLC.,JOHN DOE", keys=("ACME LLC.", "JOHN DOE")), case(2, resp="OTHER CO", keys=("OTHER CO",)), case(3, resp=None, keys=None)]))
    a, b, c = lit.cases
    assert a.match == "lead" and [(m.part, m.owner, m.outcome, m.rule) for m in a.matches] == [("ACME LLC.", "ACME LLC", "normalization_match", "N2")]
    assert (b.match, b.matches, c.match) == ("none", (), "not_comparable")
    assert {"name_match_not_identity", "owners_from_all_registrations"} <= codes(lit)


def test_no_owner_names_means_not_comparable_and_no_match_caveat():
    lit = build_litigation(answer(), FakeCG(owners=[], cases=[case()]))
    assert lit.cases[0].match == "not_comparable" and "name_match_not_identity" not in codes(lit)


def test_no_cases_is_not_a_statement_that_none_was_ever_brought():
    lit = build_litigation(answer(), FakeCG(cases=[]))
    assert lit.cases == () and lit.counts.cases == 0 and "no_cases_recorded" in codes(lit) and "case_not_finding" not in codes(lit)


def test_more_cases_than_listed_is_flagged():
    lit = build_litigation(answer(), FakeCG(cases=[case(1)], counts=[dict(caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding=None, n=300)]))
    assert lit.counts.cases == 300 and len(lit.cases) == 1 and "truncated" in codes(lit)


# ---- tool views and contract -------------------------------------------------------------------------------------------------

ARGS = {"address": "1 Main St", "borough": "Manhattan"}


def vtool(**kw): return T.make_open_violations_tool(FakeClient(resolved()), FakeGraph(), FakeCG(**kw))
def ltool(**kw): return T.make_litigation_cases_tool(FakeClient(resolved()), FakeGraph(), FakeCG(**kw))


def test_tool_names_and_descriptions_tell_the_model_the_rules():
    v, lt = vtool(), ltool()
    vt, ltx = " ".join(v.description.split()), " ".join(lt.description.split())
    assert v.name == "open_violations" and lt.name == "litigation_cases"
    assert "never add classes into one severity number" in vt and "rate is unavailable" in vt
    assert "After Inquest or After Trial" in ltx and 'Never call a respondent "the owner"' in ltx


def test_violations_tool_output_has_counts_by_class_and_no_total_or_score_keys():
    out = vtool(groups=[g("1", "A", "Open", 3), g("1", "B", "Open", 1)]).invoke(ARGS)
    assert out["status"] == "ok" and [(x["violationClass"], x["n"]) for x in out["violations"][0]["groups"]] == [("A", 3), ("B", 1)]
    assert out["violations_rate"] == {"open": 4, "units": 24, "perUnit": 0.167, "unitsSource": "PLUTO (release 26v1), lot-wide",
                                      "byClass": [{"violationClass": "A", "open": 3, "perUnit": 0.125}, {"violationClass": "B", "open": 1, "perUnit": 0.042}]}
    assert not {"score", "severity", "total", "grade"} & (set(out["violations"][0]) | set(out["violations_rate"]))


def test_litigation_tool_output_marks_findings_and_leads_and_caps_the_list():
    cs = [case(i, opened=f"2020-01-{i:02d}") for i in range(1, 6)] + [case(9, finding="After Trial", findingDate="2016-07-25")]
    out = T.litigation_to_dict(build_litigation(answer(), FakeCG(cases=cs, owners=[dict(name="ACME LLC")])), max_cases=2)
    assert len(out["cases"]) == 2 and out["case_counts"]["cases"] == 6 and "cases_capped" in {c["code"] for c in out["caveats"]}
    full = ltool(cases=[case(9, finding="After Trial")], owners=[dict(name="ACME LLC")]).invoke(ARGS)
    k = full["cases"][0]
    assert k["isHarassmentFinding"] is True and k["respondentMatch"] == "lead" and not {"owner", "is_owner", "same_party"} & set(k)


def test_tool_errors_are_answers_not_exceptions():
    for make in (T.make_open_violations_tool, T.make_litigation_cases_tool):
        out = make(FakeClient(error=RuntimeError("x")), FakeGraph(), FakeCG()).invoke(ARGS)
        assert out["status"] == "error" and "RuntimeError" in out["message"]


def test_assemble_points_at_the_new_sections_and_carries_caveats():
    out = vtool(groups=[g("1", "A", "Open", 3)]).invoke(ARGS)
    m = ModelAnswer(kind="violations", summary="Three class A violations are open.", facts=[
        ModelFact(statement="3 class A violations are open.", evidence=[EvidenceRef(section="violations")]),
        ModelFact(statement="That is 0.125 per unit.", evidence=[EvidenceRef(section="violations_rate")])])
    a = assemble(m, [out])
    assert not any(f.unresolved for f in a.facts) and a.facts[1].evidence[0].data["open"] == 3
    assert {"cited_not_fault", "open_at_snapshot"} <= a.caveat_codes
    lo = ltool(cases=[case()]).invoke(ARGS)
    a = assemble(ModelAnswer(kind="litigation", summary="One case.", facts=[
        ModelFact(statement="One case.", evidence=[EvidenceRef(section="case_counts")]), ModelFact(statement="Case 1.", evidence=[EvidenceRef(section="cases")])]), [lo])
    assert not any(f.unresolved for f in a.facts) and "harassment_finding_definition" in a.caveat_codes


def test_adding_classes_into_one_number_is_an_ungrounded_number():
    out = vtool(groups=[g("1", "A", "Open", 3), g("1", "B", "Open", 2)]).invoke(ARGS)
    assert ungrounded_numbers("3 class A and 2 class B are open", [out]) == []
    assert ungrounded_numbers("7 open violations in all", [out]) == ["7"]


def test_neo4j_conditions_graph_reads_are_parameterized_and_limited():
    seen = []

    class Rec:
        def __init__(self, d): self._d = d
        def data(self): return self._d

    class Res:
        records = [Rec(dict(bin="1", violationClass="A", status="Open", n=1, oldest=None, caseOpenDate=None, findingDate=None))]

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params))
            return Res()

    cg = C.Neo4jConditionsGraph(Drv(), "watchline")
    cg.violation_groups("2032070010")
    cg.cases("2032070010")
    cg.case_counts("2032070010")
    for q, params in seen:
        assert q.timeout and "$bbl" in q.text and "2032070010" not in q.text and "$limit" in q.text and params["bbl"] == "2032070010"
