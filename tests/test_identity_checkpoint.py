"""Identity checkpoint, step 1: links, decisions and the portfolio effect. Pure functions over fake rows; no graph, no model."""
import dataclasses

import pytest

from watchline.identity.checkpoint import Decision, Evidence, Link, Lot, Party, build_checkpoint

# Fake rows shaped like the demo: a main party of 55 lots and 176 units (54 lots of 3 units, one of 14) and a small party of 1 lot, 3 units.
MAIN = Party("MAIN NAME", tuple(Lot(f"2000000{i:03d}", 14 if i == 0 else 3) for i in range(55)))
TYPO = Party("MAIN NAMF", (Lot("2030370098", 3),))
OTHER = Party("OTHER NAME", (Lot("3000000001", None), Lot("3000000002", 10)))
SIDE = Party("SIDE NAME", (Lot("4000000001", 5),))

ADDR = Evidence("shared_address", "Same business address as recorded", "HPD contacts")
MASKED = Evidence("shared_address", "Same business address", "HPD contacts", setAside=True, reason="mail-drop list")
IDENT = Evidence("identity_edge", "Joined by a resolved identity", "BOR run")


def lead(a=MAIN, b=TYPO, ev=(ADDR,), kind="address", rule=None):
    return Link(a, b, (kind,), tuple(ev), rule)


def decide(link_id, what="accept", note=None):
    return Decision(link_id, what, "researcher", "2026-12-01", note)


def state(cp, link_id):
    return next(x.state for x in cp.links if x.linkId == link_id)


# ---- the demo shape ------------------------------------------------------------------------------------------------

def test_awaiting_leaves_the_portfolio_as_held():
    cp = build_checkpoint(MAIN, [lead()])
    assert state(cp, "MAIN NAME|MAIN NAMF") == "awaiting"
    assert (cp.effect.as_held.lots, cp.effect.as_held.units) == (55, 176) and cp.effect.as_decided == cp.effect.as_held
    assert cp.effect.added_lots == () and {"link_is_lead", "shared_address_not_evidence", "portfolio_run_local"} <= {c.code for c in cp.caveats}


def test_accepting_adds_the_other_partys_lots_and_units():
    cp = build_checkpoint(MAIN, [lead()], [decide("MAIN NAME|MAIN NAMF", note="same office")])
    assert state(cp, "MAIN NAME|MAIN NAMF") == "accepted"
    assert (cp.effect.as_held.lots, cp.effect.as_held.units) == (55, 176)            # the held numbers never change
    assert (cp.effect.as_decided.lots, cp.effect.as_decided.units, cp.effect.as_decided.parties) == (56, 179, 2)
    assert cp.effect.added_lots == ("2030370098",) and cp.effect.removed_lots == ()
    codes = {c.code for c in cp.caveats}
    assert "researcher_decision" in codes and "link_is_lead" not in codes
    assert cp.effect.as_decided.assumes == ("MAIN NAME|MAIN NAMF",) and cp.links[0].decision.note == "same office"


def test_rejecting_keeps_the_portfolio_and_records_the_state():
    cp = build_checkpoint(MAIN, [lead()], [decide("MAIN NAME|MAIN NAMF", "reject")])
    assert state(cp, "MAIN NAME|MAIN NAMF") == "rejected" and cp.effect.as_decided == cp.effect.as_held


# ---- identity links and the method -------------------------------------------------------------------------------------

def test_identity_links_are_held_by_the_method_and_a_rejection_removes_their_lots():
    link = Link(MAIN, OTHER, ("identity",), (IDENT,))
    held = build_checkpoint(MAIN, [link])
    assert state(held, link.linkId) == "accepted_by_method" and held.links[0].basis == "identity"
    assert (held.effect.as_held.lots, held.effect.as_held.units, held.effect.as_held.unitsMissing) == (57, 186, 1)
    rejected = build_checkpoint(MAIN, [link], [decide(link.linkId, "reject")])
    assert rejected.effect.as_decided.lots == 55 and rejected.effect.removed_lots == ("3000000001", "3000000002")
    assert "researcher_decision" in {c.code for c in rejected.caveats}


def test_a_lot_reached_by_two_accepted_links_counts_once_and_a_chain_is_followed():
    shared = Party("SHARED", (Lot("2030370098", 3),))
    links = [lead(MAIN, TYPO), lead(MAIN, shared, kind="name", rule="N2", ev=(Evidence("name_similarity", "N2", "names"),)),
             lead(TYPO, SIDE)]
    cp = build_checkpoint(MAIN, links, [decide(x.linkId) for x in links])
    assert cp.effect.as_decided.lots == 56 + 1 and cp.effect.as_decided.parties == 4    # 55 + shared lot once + side lot
    only_chain = build_checkpoint(MAIN, [lead(MAIN, TYPO), lead(TYPO, SIDE)], [decide("MAIN NAMF|SIDE NAME")])
    assert only_chain.effect.as_decided.lots == 55                                       # the second hop is not reachable without the first


# ---- set-aside evidence, unknown ids and bad decisions ------------------------------------------------------------------

def test_a_link_with_only_set_aside_evidence_is_unsupported_and_cannot_be_accepted():
    link = lead(ev=(MASKED,))
    cp = build_checkpoint(MAIN, [link])
    assert state(cp, link.linkId) == "unsupported" and "evidence_set_aside" in {c.code for c in cp.caveats}
    cp = build_checkpoint(MAIN, [link], [decide(link.linkId)])
    assert state(cp, link.linkId) == "unsupported" and [i.code for i in cp.issues] == ["accept_without_usable_evidence"]
    assert cp.effect.as_decided == cp.effect.as_held and "researcher_decision" not in {c.code for c in cp.caveats}


def test_unknown_ids_and_bad_decisions_are_reported_not_applied():
    cp = build_checkpoint(MAIN, [lead()], [decide("NOPE|NOPE"), decide("MAIN NAME|MAIN NAMF", "maybe")])
    assert [i.code for i in cp.issues] == ["unknown_link", "bad_decision"] and len(cp.decisions) == 2
    assert state(cp, "MAIN NAME|MAIN NAMF") == "awaiting"


def test_a_later_decision_replaces_an_earlier_one_and_both_stay_in_the_log():
    lid = "MAIN NAME|MAIN NAMF"
    cp = build_checkpoint(MAIN, [lead()], [decide(lid, "accept"), decide(lid, "reject", note="changed my mind")])
    assert state(cp, lid) == "rejected" and [d.decision for d in cp.decisions] == ["accept", "reject"]
    assert cp.effect.as_decided.lots == 55


def test_against_states_what_the_record_lacks():
    cp = build_checkpoint(MAIN, [lead()])
    assert cp.links[0].against == ("The names differ as recorded, and no named rule makes them equal.",
                                   "No joining record other than a shared address was found.")
    named = build_checkpoint(MAIN, [lead(rule="N2", kind="name", ev=(Evidence("name_similarity", "N2", "names"),))])
    assert named.links[0].against == () and "name_match_not_identity" in {c.code for c in named.caveats}


def test_two_links_with_one_id_are_an_error():
    with pytest.raises(ValueError):
        build_checkpoint(MAIN, [lead(), lead()])


# ---- reproducibility ---------------------------------------------------------------------------------------------------

def test_same_inputs_give_the_same_result_in_any_input_order():
    links = [lead(MAIN, TYPO), lead(MAIN, OTHER, kind="name", rule="N1", ev=(Evidence("name_similarity", "N1", "names"),)), lead(MAIN, SIDE)]
    decisions = [decide(links[0].linkId), decide(links[2].linkId, "reject")]
    a = build_checkpoint(MAIN, links, decisions)
    b = build_checkpoint(MAIN, list(reversed(links)), decisions)
    assert a == b and dataclasses.asdict(a) == dataclasses.asdict(b)
    assert [x.linkId for x in a.links] == sorted(x.linkId for x in a.links)
