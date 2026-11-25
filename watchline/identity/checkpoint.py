"""The identity checkpoint, step 1: links between landlord parties, the researcher's decisions on them, and the portfolio effect.

A pure function over plain rows (design: docs/plans/identity-checkpoint.md). It reads nothing, writes nothing and calls no model. The graph
never changes: a decision is an input, and the same parties, links and decisions always give the same result, in a fixed order.

A link is a candidate join between two parties (a landlord record, or records the graph already joined by identity). A name or address
match is a lead until the researcher decides. An accepted lead is the researcher's own inference, never a finding about ownership.
"""
from dataclasses import dataclass, field
from typing import Literal

from watchline.deeds.deeds import CAVEAT_NAME_NOT_IDENTITY, CAVEAT_SHARED_ADDRESS
from watchline.profile.profile import Caveat

LinkKind = Literal["address", "name", "contact", "identity"]
EvidenceKind = Literal["shared_address", "name_similarity", "identity_edge", "shared_contact"]
State = Literal["awaiting", "accepted", "rejected", "accepted_by_method", "unsupported"]
IN_EFFECT = ("accepted", "accepted_by_method")
DECISIONS = ("accept", "reject")

CAVEAT_LINK_IS_LEAD = Caveat("link_is_lead", "At least one link is a lead from a name or address match, awaiting the researcher's decision. It is not a finding.")
CAVEAT_RESEARCHER = Caveat("researcher_decision",
                           "At least one link was decided by the researcher. The result is the researcher's own inference, not a finding in the records.")
CAVEAT_SET_ASIDE = Caveat("evidence_set_aside",
                          "Some shared evidence was set aside because the address is masked or on the mail-drop list. A set-aside item supports nothing.")
CAVEAT_RUN_LOCAL = Caveat("portfolio_run_local", "Portfolio and network ids belong to one run and are not stable. Parties are named as recorded.")


@dataclass(frozen=True)
class Lot:
    bbl: str
    unitsRes: int | None = None     # a lot value; None when the lot has none recorded


@dataclass(frozen=True)
class Party:
    key: str                        # the name(s) as recorded; records the graph joined by identity are one party
    lots: tuple[Lot, ...] = ()
    records: int = 1                # how many landlord records the party holds (more than one when the graph joined them by identity)


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    text: str
    source: str
    setAside: bool = False          # masked or mail-drop address: shown, but it supports nothing
    reason: str | None = None


@dataclass(frozen=True)
class Link:
    a: Party
    b: Party
    kind: LinkKind
    evidence: tuple[Evidence, ...] = ()
    rule: str | None = None         # the named Q22 rule when the names compare equal (N1, N2, S1, L1, AB1)

    @property
    def linkId(self) -> str:
        return f"{self.a.key}|{self.b.key}|{self.kind}"


@dataclass(frozen=True)
class Decision:
    linkId: str
    decision: str                   # accept or reject
    decidedBy: str                  # a role, not a person's name
    decidedAt: str
    note: str | None = None


@dataclass(frozen=True)
class Issue:
    code: str                       # unknown_link, bad_decision, accept_without_usable_evidence
    linkId: str
    text: str


@dataclass(frozen=True)
class LinkOut:
    linkId: str
    a: str
    b: str
    kind: LinkKind
    basis: Literal["identity", "lead"]
    state: State
    evidence: tuple[Evidence, ...]
    against: tuple[str, ...]        # what argues against treating the parties as one, stated from the record
    rule: str | None
    decision: Decision | None       # the decision in force, when there is one


@dataclass(frozen=True)
class Footprint:
    """Distinct lots and the residential units of those lots (a lot value, never a building's), with the links it assumes."""
    lots: int
    units: int
    unitsMissing: int               # lots with no unit count recorded; they add nothing to `units`
    parties: int
    assumes: tuple[str, ...]        # linkIds in effect


@dataclass(frozen=True)
class PortfolioEffect:
    as_held: Footprint              # the graph alone: identity links only
    as_decided: Footprint           # after the researcher's decisions
    added_lots: tuple[str, ...]
    removed_lots: tuple[str, ...]


@dataclass(frozen=True)
class Checkpoint:
    anchor: str
    links: tuple[LinkOut, ...]
    decisions: tuple[Decision, ...]
    issues: tuple[Issue, ...]
    effect: PortfolioEffect
    caveats: tuple[Caveat, ...] = field(default=())


def _usable(link: Link) -> bool:
    return any(not e.setAside for e in link.evidence)


def _against(link: Link) -> tuple[str, ...]:
    out = []
    if link.kind != "identity" and link.rule is None:
        out.append("The names differ as recorded, and no named rule makes them equal.")
    usable = {e.kind for e in link.evidence if not e.setAside}
    if link.kind != "identity" and usable <= {"shared_address"}:
        out.append("No joining record other than a shared address was found.")
    if any(e.setAside for e in link.evidence):
        out.append("Some shared evidence was set aside (masked or mail-drop address).")
    return tuple(out)


def _reach(anchor: Party, links: list[Link], in_effect: set[str]) -> tuple[set[str], dict[str, Lot]]:
    """The parties reachable from the anchor through the links in effect, and their distinct lots. A lot reached twice counts once."""
    parties = {anchor.key: anchor}
    for ln in links:
        parties.setdefault(ln.a.key, ln.a)
        parties.setdefault(ln.b.key, ln.b)
    seen, todo = {anchor.key}, [anchor.key]
    while todo:
        k = todo.pop()
        for ln in links:
            if ln.linkId in in_effect and k in (ln.a.key, ln.b.key):
                other = ln.b.key if k == ln.a.key else ln.a.key
                if other not in seen:
                    seen.add(other)
                    todo.append(other)
    lots: dict[str, Lot] = {}
    for k in sorted(seen):
        for lot in parties[k].lots:
            lots.setdefault(lot.bbl, lot)
    return seen, lots


def _footprint(seen: set[str], lots: dict[str, Lot], in_effect: set[str]) -> Footprint:
    return Footprint(lots=len(lots), units=sum(x.unitsRes or 0 for x in lots.values()),
                     unitsMissing=sum(1 for x in lots.values() if x.unitsRes is None), parties=len(seen),
                     assumes=tuple(sorted(in_effect)))


def build_checkpoint(anchor: Party, links: list[Link] | tuple[Link, ...], decisions: list[Decision] | tuple[Decision, ...] = ()) -> Checkpoint:
    """Pure. Links with the researcher's decisions applied, and the portfolio as held and as decided.

    A later decision on the same link replaces an earlier one; all stay in `decisions`, in the order given. A decision on an unknown
    link, a decision that is neither accept nor reject, and an accept on a link whose evidence is all set aside are reported as issues
    and not applied.
    """
    ordered = sorted(links, key=lambda ln: ln.linkId)
    ids = [ln.linkId for ln in ordered]
    if len(set(ids)) != len(ids):
        raise ValueError("two links have the same linkId")
    by_id = {ln.linkId: ln for ln in ordered}

    issues: list[Issue] = []
    in_force: dict[str, Decision] = {}
    for d in decisions:
        if d.linkId not in by_id:
            issues.append(Issue("unknown_link", d.linkId, "No link has this id, so the decision was not applied."))
        elif d.decision not in DECISIONS:
            issues.append(Issue("bad_decision", d.linkId, f"The decision {d.decision!r} is neither accept nor reject; it was not applied."))
        elif d.decision == "accept" and not _usable(by_id[d.linkId]):
            issues.append(Issue("accept_without_usable_evidence", d.linkId,
                                "Every item of evidence on this link was set aside, so it supports no identity; the accept was not applied."))
        else:
            in_force[d.linkId] = d

    out: list[LinkOut] = []
    for ln in ordered:
        d = in_force.get(ln.linkId)
        if d is not None:
            state: State = "accepted" if d.decision == "accept" else "rejected"
        elif ln.kind == "identity":
            state = "accepted_by_method"
        elif not _usable(ln):
            state = "unsupported"
        else:
            state = "awaiting"
        out.append(LinkOut(ln.linkId, ln.a.key, ln.b.key, ln.kind, "identity" if ln.kind == "identity" else "lead", state,
                           ln.evidence, _against(ln), ln.rule, d))

    held_ids = {ln.linkId for ln in ordered if ln.kind == "identity"}
    decided_ids = {o.linkId for o in out if o.state in IN_EFFECT}
    held_seen, held_lots = _reach(anchor, ordered, held_ids)
    decided_seen, decided_lots = _reach(anchor, ordered, decided_ids)
    effect = PortfolioEffect(_footprint(held_seen, held_lots, held_ids), _footprint(decided_seen, decided_lots, decided_ids),
                             tuple(sorted(decided_lots.keys() - held_lots.keys())), tuple(sorted(held_lots.keys() - decided_lots.keys())))

    caveats = [CAVEAT_RUN_LOCAL]
    if any(o.state == "awaiting" for o in out):
        caveats.append(CAVEAT_LINK_IS_LEAD)
    if in_force:
        caveats.append(CAVEAT_RESEARCHER)
    if any(e.kind == "shared_address" for o in out for e in o.evidence):
        caveats.append(CAVEAT_SHARED_ADDRESS)
    if any(o.kind == "name" or o.rule for o in out):
        caveats.append(CAVEAT_NAME_NOT_IDENTITY)
    if any(e.setAside for o in out for e in o.evidence):
        caveats.append(CAVEAT_SET_ASIDE)
    return Checkpoint(anchor.key, tuple(out), tuple(decisions), tuple(issues), effect, tuple(caveats))
