"""Identity checkpoint, step 3: the section, its JSON view, the decision file and the Answer. No graph, no model."""
import json

import pytest
from test_identity_graph import ADDR, BASE, FakeIG, edge, rec

from watchline.identity.checkpoint import Decision
from watchline.identity.section import (
    checkpoint_to_dict,
    decisions_from_json,
    decisions_to_json,
    identity_checkpoint,
    to_answer,
)

LID = "ACME OWNER|ACME OWNR"


def dec(what="accept", note=None, lid=LID):
    return Decision(lid, what, "researcher", "2026-12-01", note)


def answer(decisions=(), **kw):
    return to_answer(identity_checkpoint(FakeIG(**{**BASE, **kw}), "ACME OWNER", decisions))


def test_awaiting_answer_states_the_lead_and_the_held_numbers_in_words():
    a = answer()
    assert a.kind == "identity_checkpoint" and "No decision has been made yet." in a.summary
    assert "as held in the graph, 3 lots and 6 residential units (no unit count is recorded for 1 lot) across 2 landlord records" in a.summary
    link_fact, effect_fact = a.facts
    assert link_fact.statement == ("ACME OWNER and ACME OWNR are linked by a shared business address. "
                                   "A lead, awaiting the researcher's decision.")
    assert [e.section for e in link_fact.evidence] == ["links"] and [e.section for e in effect_fact.evidence] == ["portfolio_effect"]
    assert {"link_is_lead", "shared_address_not_evidence", "portfolio_run_local", "deed_links_not_read"} <= {c.code for c in a.caveats}
    assert any("HPD" in s for s in a.sources)


def test_accepted_answer_labels_the_inference_and_shows_both_footprints():
    a = answer([dec(note="same office")])
    assert "After the researcher's decisions: 4 lots and 9 residential units" in a.summary
    assert "Accepted by the researcher (decided by researcher on 2026-12-01; note: same office). This is the researcher's inference, not a finding in the records." in a.facts[0].statement
    eff = a.facts[1].evidence[0].data
    assert (eff["as_held"]["lots"], eff["as_decided"]["lots"], eff["added_lots"]) == (3, 4, ["2030370098"])
    codes = {c.code for c in a.caveats}
    assert "researcher_decision" in codes and "link_is_lead" not in codes


def test_rejected_and_ignored_decisions():
    a = answer([dec("reject")])
    assert "Rejected by the researcher" in a.facts[0].statement and "4 lots" not in a.summary
    a = answer([dec(lid="NOPE|NOPE")])
    assert any("was not applied: No link has this id" in f.statement for f in a.facts)


def test_unknown_name_and_ambiguous_name_are_not_checkpoints():
    nf = to_answer(identity_checkpoint(FakeIG(**BASE), "NOBODY"))
    assert nf.kind == "not_found" and "NOBODY" in nf.summary and nf.facts == []
    ig = FakeIG(records=[rec(1, "SAME"), rec(2, "SAME")], lots=[dict(nodeId=1, bbl="2000000001", unitsRes=3), dict(nodeId=2, bbl="3000000001", unitsRes=4)])
    amb = to_answer(identity_checkpoint(ig, "SAME"))
    assert amb.kind == "clarification" and "SAME (1 lots); SAME (1 lots)" in amb.summary and "none was chosen" in amb.summary


def test_no_links_says_so():
    ig = FakeIG(records=[rec(1, "ALONE", ADDR)], lots=[dict(nodeId=1, bbl="2000000001", unitsRes=3)])
    a = to_answer(identity_checkpoint(ig, "ALONE"))
    assert "No other landlord record is linked to it" in a.summary and len(a.facts) == 1


def test_the_sources_include_the_registrations_only_when_a_pair_rests_on_one():
    from test_identity_graph import REGS
    plain = answer()
    assert not any("registrations" in s for s in plain.sources)
    with_reg = to_answer(identity_checkpoint(FakeIG(**BASE, registrations=REGS), "ACME OWNER"))
    assert "HPD registrations (contacts listed on each registration)" in with_reg.sources
    assert "linked by a shared business address and names listed together on an HPD registration" in with_reg.facts[0].statement


def test_the_summary_does_not_claim_decisions_took_effect_when_none_was_applied():
    a = answer([dec(lid="NOPE|NOPE")])
    assert "No decision could be applied (see below)." in a.summary and "After the researcher's decisions" not in a.summary
    assert "After the researcher's decisions" in answer([dec()]).summary
    assert "No decision has been made yet." in answer().summary


def test_the_lead_caveat_and_the_no_links_wording_mention_registrations():
    from watchline.identity.checkpoint import CAVEAT_LINK_IS_LEAD
    assert "shared-registration" in CAVEAT_LINK_IS_LEAD.text
    ig = FakeIG(records=[rec(1, "ALONE", ADDR)], lots=[dict(nodeId=1, bbl="2000000001", unitsRes=3)])
    assert "a shared business address, a similar name or a shared registration" in to_answer(identity_checkpoint(ig, "ALONE")).summary


def test_the_answer_is_deterministic_and_the_json_view_has_no_score_keys():
    assert answer([dec()]) == answer([dec()])
    d = checkpoint_to_dict(identity_checkpoint(FakeIG(**BASE), "ACME OWNER", [dec()]))
    assert not {"score", "total", "same_party", "owner"} & set(json.dumps(d).replace('"', " ").split())
    assert d["status"] == "ok" and d["links"][0]["state"] == "accepted" and d["portfolio_effect"]["as_held"]["lots"] == 3


def test_name_links_say_the_names_differ_when_no_rule_applies():
    base = dict(BASE, records=[rec(1, "ACME OWNER"), rec(2, "ACME OWNER"), rec(3, "OTHER NAME")], edges=[edge(1, 3, "NAME", 1.0)])
    a = answer(**base)
    assert "are linked by the network method's name comparison." in a.facts[0].statement and "name_match_not_identity" in {c.code for c in a.caveats}
    ln = checkpoint_to_dict(identity_checkpoint(FakeIG(**{**BASE, **base}), "ACME OWNER"))["links"][0]
    assert ln["against"][0].startswith("The names differ as recorded")


# ---- the decision file -------------------------------------------------------------------------------------------------

def test_decision_file_round_trips_in_order():
    ds = [dec("accept", "a"), dec("reject", None)]
    assert decisions_from_json(decisions_to_json(ds)) == ds
    assert decisions_to_json(ds) == decisions_to_json(list(ds))                      # stable text, so a saved report diffs cleanly


@pytest.mark.parametrize("text", ["{}", "[1]",
                                  '[{"linkId": "x", "decision": "accept", "decidedBy": null, "decidedAt": null}]',
                                  '[{"linkId": "x", "decision": "accept", "decidedBy": "  ", "decidedAt": "d"}]', '[{"linkId": "x"}]', '[{"linkId": "x", "decision": "accept", "decidedBy": "r", "decidedAt": "d", "extra": 1}]',
                                  '[{"linkId": "x", "decision": 1, "decidedBy": "r", "decidedAt": "d"}]'])
def test_bad_decision_files_are_errors(text):
    with pytest.raises(ValueError):
        decisions_from_json(text)


# ---- live (no model) -----------------------------------------------------------------------------------------------------

def test_live_bahumi_answer_awaiting_then_accepted(live_graph):
    lid = "YONATAN BAHUMI|YONATAN BADHUMI"
    a = to_answer(identity_checkpoint(live_graph, "YONATAN BAHUMI"))
    assert "as held in the graph, 55 lots and 176 residential units across 6 landlord records" in a.summary and "No decision has been made yet." in a.summary
    assert "1 possible link to other landlord records, 1 awaiting a decision" in a.summary
    assert any(f.statement.startswith("YONATAN BAHUMI and YONATAN BADHUMI are linked by a shared business address and names listed together on an HPD registration. A lead") for f in a.facts)
    b = to_answer(identity_checkpoint(live_graph, "YONATAN BAHUMI", [Decision(lid, "accept", "researcher", "2026-12-01")]))
    assert "After the researcher's decisions: 56 lots and 179 residential units." in b.summary and "researcher_decision" in {c.code for c in b.caveats}


def test_a_note_may_be_null_but_the_four_required_fields_may_not():
    ok = decisions_from_json('[{"linkId": "x", "decision": "accept", "decidedBy": "researcher", "decidedAt": "2026-12-01", "note": null}]')
    assert ok[0].note is None
