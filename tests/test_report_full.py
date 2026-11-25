"""The whole report graph on fakes: order, early stops, the two pauses, restart, determinism, and that nothing is read twice. No graph, no model."""
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_conditions import FakeCG, case, g
from test_contacts import FakeCG as ContactCG
from test_contacts import crow
from test_deeds import FakeDG, drow
from test_identity_graph import ADDR, FakeIG, edge, lot, rec
from test_profile import BUILDINGS, FakePG
from test_registration import FakeRG, owner, row
from test_timeline import FakeTG, trow

from watchline.geosupport.geosupport import Outcome, Result
from watchline.report.graph import SECTIONS, ReportDeps, build_report_graph, pending

BBL = "1000010001"       # what `resolved()` returns


class AllReads:
    """One object serving every read the report makes from the graph, built from the fakes the section tests use."""
    def __init__(self, deeds=(), timeline=(), contacts=(), groups=(), cases=()):
        self.reg = FakeRG(rows=[row()], owners=[owner()])
        self.dg, self.tl = FakeDG(deeds), FakeTG(timeline)
        self.con, self.cond = ContactCG(contacts, rows=[row()]), FakeCG(groups=groups, cases=cases, owners=[dict(name="ACME LLC")])

    def lot(self, bbl): return self.cond.lot(bbl)
    def buildings(self, bbl): return self.cond.buildings(bbl)
    def registrations(self, bbl): return self.reg.registrations(bbl)
    def owners(self, bbl): return self.reg.owners(bbl)
    def deeds(self, bbl): return self.dg.deeds(bbl)
    def timeline(self, bbl, since, until): return self.tl.timeline(bbl, since, until)
    def deed_counts(self, bbl, since, until): return self.tl.deed_counts(bbl, since, until)
    def contacts(self, bbl): return self.con.contacts(bbl)
    def violation_groups(self, bbl): return self.cond.violation_groups(bbl)
    def cases(self, bbl): return self.cond.cases(bbl)
    def case_counts(self, bbl): return self.cond.case_counts(bbl)


def identity_rows(covering=(("ACME OWNER", BBL),), lead=True):
    """Landlord records: ACME OWNER covers the lot (and one more lot); ACME OWNR is linked to it by a shared address."""
    records = [rec(1, "ACME OWNER", ADDR), rec(2, "ACME OWNR", ADDR)]
    lots = [lot(1, BBL, 24), lot(1, "2000000002", 3), lot(2, "2030370098", 3)]
    for n, (name, bbl) in enumerate(covering):
        if name not in ("ACME OWNER", "ACME OWNR"):
            records.append(rec(10 + n, name))
            lots.append(lot(10 + n, bbl, 5))
    return dict(records=records, lots=lots, edges=[edge(1, 2)] if lead else [])


def make(ig=None, reads=None, client=None, graph=None, saver=None):
    ig = ig if ig is not None else FakeIG(**identity_rows())
    client = client or FakeClient(resolved())
    deps = ReportDeps(client, graph or FakeGraph(), FakePG(buildings=BUILDINGS), reads or AllReads(deeds=[drow()], timeline=[trow()], contacts=[crow()], groups=[g()],
                                                                                                    cases=[case()]), ig)
    return build_report_graph(deps, saver or InMemorySaver()), {"configurable": {"thread_id": "t"}}, deps


START = {"text": "1 Main St", "borough": "Manhattan", "generated_at": "2026-12-01 demo"}


def accept(link_id="ACME OWNER|ACME OWNR", what="accept"):
    return {"decisions": [{"linkId": link_id, "decision": what, "decidedBy": "researcher", "decidedAt": "2026-12-01", "note": "same office"}]}


def keys(report):
    return [s["key"] for s in report["sections"]]


# ---- the run ------------------------------------------------------------------------------------------------------------------

def test_a_lot_with_no_lead_runs_straight_through_in_reading_order():
    g_, cfg, _ = make(ig=FakeIG(**identity_rows(lead=False)))
    r = g_.invoke(START, cfg)
    assert pending(r) == []
    rep = r["report"]
    assert rep["status"] == "ok" and rep["generated_at"] == "2026-12-01 demo" and rep["bbl"] == BBL and rep["landlord"] == "ACME OWNER"
    assert keys(rep) == [k for k, *_ in SECTIONS] == ["building", "owner", "entity", "identity", "deeds", "violations", "litigation", "web"]
    kinds = {s["key"]: s["answer"]["kind"] for s in rep["sections"]}
    assert kinds == {"building": "profile", "owner": "registration", "entity": "not_covered", "identity": "identity_checkpoint", "deeds": "timeline",
                     "violations": "violations", "litigation": "litigation", "web": "not_covered"}
    assert {s["question"] for s in rep["sections"]} == {"About this building", "Who is my landlord?", "How many properties and where?", "Do they hold or sell?",
                                                       "What are the conditions?", "Is there news?"}
    assert all(s["answer"]["summary"] for s in rep["sections"]) and rep["sources"]


def test_the_address_is_resolved_once_and_every_section_reads_the_same_lot():
    g_, cfg, deps = make(ig=FakeIG(**identity_rows(lead=False)))
    g_.invoke(START, cfg)
    assert len(deps.client.calls) == 1


def test_a_lead_pauses_for_a_decision_and_the_decision_changes_only_the_identity_section():
    saver = InMemorySaver()
    g_, cfg, deps = make(saver=saver)
    first = g_.invoke(START, cfg)
    (p,) = pending(first)
    assert p["kind"] == "identity_checkpoint_decision" and [x["linkId"] for x in p["links"]] == ["ACME OWNER|ACME OWNR"]
    assert "report" not in first and set(first["parts"]) == {"building", "owner", "deeds", "entity", "identity"}       # sections so far are visible while it waits
    done = g_.invoke(Command(resume=accept()), cfg)["report"]
    plain, _, _ = make(ig=FakeIG(**identity_rows(lead=False)))
    again = plain.invoke(START, {"configurable": {"thread_id": "other"}})["report"]
    for k in ("building", "owner", "deeds", "violations", "litigation"):
        assert next(s for s in done["sections"] if s["key"] == k) == next(s for s in again["sections"] if s["key"] == k)
    ident = next(s for s in done["sections"] if s["key"] == "identity")["answer"]
    assert "After the researcher's decisions" in ident["summary"] and done["decisions"] == accept()["decisions"]
    assert done["checkpoint"]["portfolio_effect"]["as_held"]["lots"] == 2 and done["checkpoint"]["portfolio_effect"]["as_decided"]["lots"] == 3
    assert '"decision": "accept"' in done["decision_log"]


def test_nothing_is_read_again_on_resume_except_the_final_identity_pass():
    g_, cfg, deps = make()
    g_.invoke(START, cfg)
    g_.invoke(Command(resume=accept()), cfg)
    assert len(deps.client.calls) == 1 and deps.ig.calls.count("records_named") == 2           # propose, then finish


def test_a_bad_answer_is_asked_again_and_a_good_one_finishes():
    g_, cfg, _ = make()
    g_.invoke(START, cfg)
    (p,) = pending(g_.invoke(Command(resume=accept(what="approve")), cfg))
    assert "must be accept or reject" in p["error"]
    assert "report" in g_.invoke(Command(resume=accept()), cfg)


def test_the_same_decisions_give_the_same_report_and_a_new_graph_object_can_resume():
    saver = InMemorySaver()
    g1, cfg, _ = make(saver=saver)
    g1.invoke(START, cfg)
    g2, _, _ = make(saver=saver)                                        # a restart in the same process
    a = g2.invoke(Command(resume=accept()), cfg)["report"]
    g3, cfg3, _ = make()
    g3.invoke(START, cfg3)
    assert a == g3.invoke(Command(resume=accept()), cfg3)["report"]


# ---- early stops -----------------------------------------------------------------------------------------------------------

def test_a_missing_borough_stops_before_anything_is_read():
    g_, cfg, deps = make()
    rep = g_.invoke({"text": "1 Main St", "generated_at": "x"}, cfg)["report"]
    assert rep["status"] == "needs_input" and rep["needs_input"]["status"] == "needs_borough" and rep["sections"] == []
    assert deps.ig.calls == [] and len(deps.client.calls) == 0


def test_an_address_geosupport_cannot_find_stops_with_the_reason():
    nf = Result(outcome=Outcome.STREET_NOT_RECOGNIZED, grc="11", typed="1 Main St")
    g_, cfg, deps = make(client=FakeClient(nf))
    rep = g_.invoke(START, cfg)["report"]
    assert rep["needs_input"]["status"] == "not_found" and "return code 11" in rep["needs_input"]["message"] and rep["sections"] == []


def test_a_lot_the_graph_does_not_hold_stops():
    class NoLot(FakeGraph):
        def has_lot(self, bbl): return False
    g_, cfg, _ = make(graph=NoLot())
    rep = g_.invoke(START, cfg)["report"]
    assert rep["needs_input"]["status"] == "not_in_graph" and rep["sections"] == []


# ---- the landlord step -----------------------------------------------------------------------------------------------------

def test_a_lot_no_landlord_record_covers_says_so_and_the_rest_of_the_report_still_runs():
    g_, cfg, _ = make(ig=FakeIG(**dict(identity_rows(), lots=[lot(1, "2000000002", 3), lot(2, "2030370098", 3)])))
    r = g_.invoke(START, cfg)
    rep = r["report"]
    assert pending(r) == [] and rep["landlord"] is None and rep["checkpoint"] is None
    ident = next(s for s in rep["sections"] if s["key"] == "identity")["answer"]
    assert ident["kind"] == "not_found" and "does not mean" not in ident["summary"] and "No landlord record in the graph covers this lot" in ident["summary"]
    assert {"violations", "litigation", "web"} <= set(keys(rep))


def test_several_landlord_names_on_the_lot_ask_which_one():
    rows = identity_rows(covering=(("ACME OWNER", BBL), ("OTHER NAME", BBL)), lead=False)
    g_, cfg, _ = make(ig=FakeIG(**rows))
    (p,) = pending(g_.invoke(START, cfg))
    assert p["kind"] == "choose_landlord" and p["names"] == ["ACME OWNER", "OTHER NAME"]
    (p,) = pending(g_.invoke(Command(resume={"name": "NOT A NAME"}), cfg))
    assert p["error"] and p["kind"] == "choose_landlord"
    rep = g_.invoke(Command(resume={"name": "OTHER NAME"}), cfg)["report"]
    assert rep["landlord"] == "OTHER NAME"
    assert "OTHER NAME" in next(s for s in rep["sections"] if s["key"] == "identity")["answer"]["summary"]


@pytest.mark.parametrize("key", ["entity", "web"])
def test_steps_without_a_tool_are_listed_as_not_covered(key):
    g_, cfg, _ = make(ig=FakeIG(**identity_rows(lead=False)))
    sec = next(s for s in g_.invoke(START, cfg)["report"]["sections"] if s["key"] == key)
    assert sec["answer"]["kind"] == "not_covered" and sec["answer"]["summary"].startswith("Not yet covered:")


# ---- live (no model): the demo address -----------------------------------------------------------------------------------------

def test_live_2141_washington_avenue_end_to_end(live_report_deps):
    """Probed 2026-11-25: the lot the BADHUMI record covers. One lead (BAHUMI, address and registration 205148); accepting it grows the portfolio from 1 lot to 56."""
    g_ = build_report_graph(live_report_deps, InMemorySaver())
    cfg = {"configurable": {"thread_id": "live"}}
    first = g_.invoke({"text": "2141 Washington Avenue, Bronx", "generated_at": "live check"}, cfg)
    (p,) = pending(first)
    assert [x["linkId"] for x in p["links"]] == ["YONATAN BADHUMI|YONATAN BAHUMI"] and p["links"][0]["kinds"] == ["address", "contact"]
    held = p["portfolio_effect"]["as_held"]
    assert (held["lots"], held["units"]) == (1, 3)
    rep = g_.invoke(Command(resume={"decisions": [{"linkId": "YONATAN BADHUMI|YONATAN BAHUMI", "decision": "accept", "decidedBy": "researcher",
                                                   "decidedAt": "2026-12-01", "note": "registration 205148 lists both"}]}), cfg)["report"]
    assert rep["status"] == "ok" and rep["bbl"] == "2030370098" and rep["landlord"] == "YONATAN BADHUMI"
    decided = rep["checkpoint"]["portfolio_effect"]["as_decided"]
    assert (decided["lots"], decided["units"]) == (56, 179)
    by = {s["key"]: s["answer"] for s in rep["sections"]}
    assert "2141 WASHINGTON AVE LLC" in " ".join(f["statement"] for f in by["owner"]["facts"])
    assert "9 deeds recorded: 7 record an amount of 0; 2 record another amount" in " ".join(f["statement"] for f in by["deeds"]["facts"])
    assert by["entity"]["kind"] == "not_covered" and by["web"]["kind"] == "not_covered"
