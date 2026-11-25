"""The report graph's identity checkpoint: pause, resume, reproduce. Fake graph rows for the logic; live (no model) for the demo name."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_identity_graph import BASE, FakeIG, rec

from watchline.identity.section import decisions_from_json, identity_checkpoint, to_answer
from watchline.report.graph import PROMPT, build_report_graph, pending

LID = "ACME OWNER|ACME OWNR|address"


def d(what="accept", lid=LID, note=None, by="researcher", at="2026-12-01"):
    return {"linkId": lid, "decision": what, "decidedBy": by, "decidedAt": at, **({"note": note} if note else {})}


def start(ig=None, name="ACME OWNER", thread="t"):
    ig = ig or FakeIG(**BASE)
    g = build_report_graph(ig, InMemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    return g, cfg, ig, g.invoke({"name": name}, cfg)


def test_the_graph_pauses_with_the_leads_awaiting_a_decision():
    _, _, _, r = start()
    (p,) = pending(r)
    assert p["kind"] == PROMPT and p["name"] == "ACME OWNER" and p["error"] is None
    assert [x["linkId"] for x in p["links"]] == [LID] and p["links"][0]["state"] == "awaiting" and p["links"][0]["evidence"]
    assert p["portfolio_effect"]["as_held"]["lots"] == 3 and "link_is_lead" in {c["code"] for c in p["caveats"]}
    assert "decision_log" not in r                                  # not finished


def test_resume_with_a_decision_finishes_and_matches_the_plain_function():
    g, cfg, ig, _ = start()
    r = g.invoke(Command(resume={"decisions": [d(note="same office")]}), cfg)
    assert pending(r) == []
    direct = to_answer(identity_checkpoint(FakeIG(**BASE), "ACME OWNER", decisions_from_json(json.dumps([d(note="same office")]))))
    assert r["answer"] == direct.model_dump()                      # the graph adds the pause, not a different result
    assert "After the researcher's decisions: 4 lots and 9 residential units" in r["answer"]["summary"]
    assert decisions_from_json(r["decision_log"]) == decisions_from_json(json.dumps([d(note="same office")]))


def test_the_pausing_node_does_not_read_the_graph_again_on_resume():
    g, cfg, ig, _ = start()
    reads_at_pause = ig.calls.count("records_named")
    assert reads_at_pause == 1                                      # propose read once
    g.invoke(Command(resume={"decisions": [d()]}), cfg)
    assert ig.calls.count("records_named") == 2                     # only finish read again; propose did not re-run


def test_an_empty_answer_leaves_every_link_awaiting():
    g, cfg, _, _ = start()
    r = g.invoke(Command(resume={"decisions": []}), cfg)
    assert pending(r) == [] and "No decision has been made yet." in r["answer"]["summary"] and json.loads(r["decision_log"]) == []


def test_a_rejection_keeps_the_held_portfolio():
    g, cfg, _, _ = start()
    r = g.invoke(Command(resume={"decisions": [d("reject", note="different office")]}), cfg)
    assert "Rejected by the researcher" in r["answer"]["facts"][0]["statement"] and "4 lots" not in r["answer"]["summary"]


@pytest.mark.parametrize("bad", ["accept", {"decisions": "accept"}, {"decisions": [{"linkId": LID}]},
                                 {"decisions": [{**d(), "extra": 1}]}])
def test_a_bad_answer_goes_back_to_the_same_pause_with_the_reason(bad):
    g, cfg, _, _ = start()
    r = g.invoke(Command(resume=bad), cfg)
    (p,) = pending(r)
    assert p["kind"] == PROMPT and p["error"]                       # asked again, with why
    r = g.invoke(Command(resume={"decisions": [d()]}), cfg)         # a good answer then finishes
    assert pending(r) == [] and "4 lots" in r["answer"]["summary"]


def test_an_unknown_link_id_is_reported_in_the_answer_not_applied():
    g, cfg, _, _ = start()
    r = g.invoke(Command(resume={"decisions": [d(lid="NOPE|NOPE|address")]}), cfg)
    assert any("was not applied" in f["statement"] for f in r["answer"]["facts"])
    assert "4 lots" not in r["answer"]["summary"]


def test_no_links_or_an_unknown_name_never_pause():
    alone = FakeIG(records=[rec(1, "ALONE")], lots=[dict(nodeId=1, bbl="2000000001", unitsRes=3)])
    _, _, _, r = start(alone, "ALONE")
    assert pending(r) == [] and "No other landlord record is linked" in r["answer"]["summary"]
    _, _, _, r = start(FakeIG(**BASE), "NOBODY", thread="t2")
    assert pending(r) == [] and r["answer"]["kind"] == "not_found"


def test_two_runs_with_the_same_decisions_give_the_same_result():
    out = []
    for thread in ("a", "b"):
        g, cfg, _, _ = start(thread=thread)
        out.append(g.invoke(Command(resume={"decisions": [d()]}), cfg))
    assert out[0]["answer"] == out[1]["answer"] and out[0]["decision_log"] == out[1]["decision_log"]


def test_a_paused_run_survives_a_new_graph_object_on_the_same_checkpointer():
    saver = InMemorySaver()
    cfg = {"configurable": {"thread_id": "t"}}
    build_report_graph(FakeIG(**BASE), saver).invoke({"name": "ACME OWNER"}, cfg)
    r = build_report_graph(FakeIG(**BASE), saver).invoke(Command(resume={"decisions": [d()]}), cfg)     # a restart in the same process
    assert pending(r) == [] and "4 lots" in r["answer"]["summary"]


def test_live_bahumi_pause_and_resume(live_graph):
    g = build_report_graph(live_graph, InMemorySaver())
    cfg = {"configurable": {"thread_id": "live"}}
    r = g.invoke({"name": "YONATAN BAHUMI"}, cfg)
    (p,) = pending(r)
    assert [x["linkId"] for x in p["links"]] == ["YONATAN BAHUMI|YONATAN BADHUMI|address"]
    assert (p["portfolio_effect"]["as_held"]["lots"], p["portfolio_effect"]["as_held"]["units"]) == (55, 176)
    r = g.invoke(Command(resume={"decisions": [d(lid=p["links"][0]["linkId"], note="same office")]}), cfg)
    assert "After the researcher's decisions: 56 lots and 179 residential units." in r["answer"]["summary"]
