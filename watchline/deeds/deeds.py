"""Address to the most recent deed(s) and the HPD registered owners, with name and address agreement (Q3).

Resolution is Q1.3 and the registered owners are Q2. This adds the deeds recorded on the lot: those with the latest recorded date
(ties are all returned, none chosen), every grantee on each, and a string comparison of each grantee against each registered owner.

Agreement is a recorded comparison, never a finding that two records are one party. A deed shows a transfer of title, not a sale
(an amount of 0 is common). The deed and the registration come from different snapshots and nothing is inferred about which is newer.
"""
from dataclasses import dataclass, field
from typing import Protocol

from watchline.deeds.names import address_agreement, name_agreement
from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import CAVEAT_TRUNCATED, HPD, MAX_GROUPS, Caveat
from watchline.registration import registration as R
from watchline.registration.registration import Neo4jRegistrationGraph, RegistrationGraph, Registrations

MAX_ROWS = MAX_GROUPS
DEED_TYPES = ("DEED", "DEED, TS", "DEED, LE", "DEED, RC", "DEEDO", "DEEDP", "CORRD", "CONDEED")   # as the graph stores them; DEED COR is not a deed
ACRIS = "ACRIS deeds and parties (data through 2026-05-31)"
ACRIS_SNAPSHOT, HPD_SNAPSHOT = "2026-05-31", R.SNAPSHOT_DATE

CAVEAT_NAME_NOT_IDENTITY = Caveat("name_match_not_identity",
                                  ("Name agreement is a comparison of recorded strings, not a finding that a deed grantee and a "
                                   "registered owner are the same party. A difference is not a finding either."))
CAVEAT_RECORDED = Caveat("most_recent_by_recorded",
                         "Most recent means the latest recorded date, not the date written on the deed.")
CAVEAT_NOT_SALE = Caveat("deed_not_sale",
                         "A deed records a transfer of title, not that a sale took place. An amount of 0 is common and is not a free sale.")
CAVEAT_MULTI_LOT = Caveat("multi_lot_deed",
                          "At least one deed also names other tax lots, so it is not specific to this lot.")
CAVEAT_TIED = Caveat("tied_deeds",
                     "More than one deed was recorded on the latest date. All are shown and none is chosen.")
CAVEAT_SNAPSHOTS = Caveat("snapshots_differ",
                          (f"Deeds are read from a snapshot through {ACRIS_SNAPSHOT} and registrations through {HPD_SNAPSHOT}. "
                           "They describe different moments, and nothing here says which is newer."))
CAVEAT_NO_DEED = Caveat("no_deed_found",
                        "No deed is recorded for this lot in the data. That does not mean the lot never changed hands.")
CAVEAT_SHARED_ADDRESS = Caveat("shared_address_not_evidence",
                               ("A shared address can be a mail drop or a representative's office. It is not evidence that two "
                                "records are one party."))
CAVEAT_NO_GRANTEE = Caveat("deed_without_grantee", "At least one deed has no grantee recorded.")


@dataclass(frozen=True)
class Grantee:
    name: str | None
    mailingAddress: str | None
    addressLine2: str | None
    zip: str | None


@dataclass(frozen=True)
class Deed:
    documentId: str
    docType: str
    docDate: str | None          # the date written on the deed; absent when ACRIS has none
    recordedDate: str
    amount: int | None           # as recorded; 0 is not a free sale
    otherLots: int               # how many other graph lots the deed names
    grantees: tuple[Grantee, ...]


@dataclass(frozen=True)
class Pair:
    """One grantee against one registered owner. Name and address agreement are separate fields."""
    documentId: str
    grantee: str | None
    owner: str | None
    ownerType: str
    nameOutcome: str             # exact_normalized, normalization_match, different, not_comparable
    nameRule: str | None         # N1 or N2 when matched
    addressOutcome: str          # same, differs, absent (rule A1)
    granteeAddress: tuple[str | None, str | None, str | None]   # street line, second line, ZIP: what each side recorded, shown so
    ownerAddress: tuple[str | None, str | None, str | None]     # pairs that differ only in address can be told apart


@dataclass(frozen=True)
class DeedComparison:
    resolution: Answer
    lot: dict | None = None
    deeds: tuple[Deed, ...] = ()
    owners: tuple[R.RegisteredOwner, ...] = ()
    pairs: tuple[Pair, ...] = ()
    caveats: tuple[Caveat, ...] = field(default=())
    sources: tuple[str, ...] = ()


class DeedGraph(Protocol):
    def deeds(self, bbl: str) -> list[dict]: ...


class Neo4jDeedGraph(Neo4jRegistrationGraph):
    """The registration reads plus the deed read, so one object serves both tools. Same limits: read-only, parameterized, timed out."""

    def deeds(self, bbl: str) -> list[dict]:
        """One row per deed and grantee for the deeds with the latest recorded date on the lot; a deed with no grantee gets one null row."""
        rows = self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_DEED]->(d:Deed WHERE d.docType IN $types) "
                          "WITH max(d.recordedDate) AS latest "
                          "MATCH (:Lot {bbl: $bbl})-[:HAS_DEED]->(d:Deed WHERE d.docType IN $types AND d.recordedDate = latest) "
                          "OPTIONAL MATCH (d)-[:HAS_GRANTEE]->(g:Grantee) "
                          "RETURN d.documentId AS documentId, d.docType AS docType, d.docDate AS docDate, "
                          "d.recordedDate AS recordedDate, d.amount AS amount, "
                          "COUNT { (d)<-[:HAS_DEED]-(:Lot) } - 1 AS otherLots, g.name AS name, "
                          "g.mailingAddress AS mailingAddress, g.addressLine2 AS addressLine2, g.zip AS zip "
                          "ORDER BY documentId, name, mailingAddress LIMIT $limit",
                          bbl=bbl, types=list(DEED_TYPES), limit=MAX_ROWS)
        return [{**r, "docDate": R._iso(r["docDate"]), "recordedDate": R._iso(r["recordedDate"])} for r in rows]   # the driver returns dates


def _deeds(rows: list[dict]) -> tuple[Deed, ...]:
    by_id: dict[str, dict] = {}
    for r in rows:
        d = by_id.setdefault(r["documentId"], dict(row=r, grantees=[]))
        if any(r.get(k) for k in ("name", "mailingAddress")):
            g = Grantee(r.get("name") or None, r.get("mailingAddress") or None, r.get("addressLine2") or None, r.get("zip") or None)
            if g not in d["grantees"]:           # exact duplicate party rows are one party
                d["grantees"].append(g)
    return tuple(Deed(k, v["row"]["docType"], v["row"].get("docDate") or None, v["row"]["recordedDate"], v["row"].get("amount"),
                      max(v["row"].get("otherLots") or 0, 0), tuple(v["grantees"])) for k, v in by_id.items())


def _owners(regs: Registrations) -> tuple[R.RegisteredOwner, ...]:
    seen: list[R.RegisteredOwner] = []
    for b in regs.buildings:
        for g in b.registrations:
            for o in g.owners:
                if o not in seen:
                    seen.append(o)
    return tuple(seen)


def _pairs(deeds: tuple[Deed, ...], owners: tuple[R.RegisteredOwner, ...]) -> tuple[Pair, ...]:
    out = []
    for d in deeds:
        for g in d.grantees:
            for o in owners:
                outcome, rule = name_agreement(g.name, o.name)
                out.append(Pair(d.documentId, g.name, o.name, o.contactType, outcome, rule,
                                address_agreement(g.mailingAddress, g.zip, o.mailingAddress, o.zip),
                                (g.mailingAddress, g.addressLine2, g.zip), (o.mailingAddress, o.addressLine2, o.zip)))
    return tuple(out)


def build_comparison(resolution: Answer, rg: RegistrationGraph, dg: DeedGraph) -> DeedComparison:
    """Pure given the graph rows. Registrations decide resolution and owners; the deed read is made only for a lot we hold."""
    regs = R.build_registrations(resolution, rg)
    # Q2's period and other-roles caveats are about registration dates and roles this answer does not show.
    caveats = [c for c in regs.caveats if c not in (R.CAVEAT_PERIOD, R.CAVEAT_OTHER_ROLES)]
    if regs.lot is None:
        return DeedComparison(resolution, caveats=tuple(caveats))

    rows = dg.deeds(resolution.bbl)
    deeds, owners = _deeds(rows), _owners(regs)
    pairs = _pairs(deeds, owners)
    if not deeds:
        return DeedComparison(resolution, lot=regs.lot, owners=owners, caveats=(*caveats, CAVEAT_NO_DEED), sources=(HPD,))
    caveats += [CAVEAT_RECORDED, CAVEAT_SNAPSHOTS]
    if pairs:
        caveats.append(CAVEAT_NAME_NOT_IDENTITY)
    if any(d.amount == 0 for d in deeds):
        caveats.append(CAVEAT_NOT_SALE)
    if any(d.otherLots for d in deeds):
        caveats.append(CAVEAT_MULTI_LOT)
    if len(deeds) > 1:
        caveats.append(CAVEAT_TIED)
    if any(not d.grantees for d in deeds):
        caveats.append(CAVEAT_NO_GRANTEE)
    if any(p.addressOutcome == "same" for p in pairs):
        caveats.append(CAVEAT_SHARED_ADDRESS)
    if len(rows) >= MAX_ROWS:
        caveats.append(CAVEAT_TRUNCATED)
    return DeedComparison(resolution, lot=regs.lot, deeds=deeds, owners=owners, pairs=pairs,
                          caveats=tuple(dict.fromkeys(caveats)), sources=(ACRIS, HPD))


def deed_vs_owner(client, graph: Graph, rg: RegistrationGraph | DeedGraph, text: str, **kw) -> DeedComparison:
    """Typed address to deeds and agreement. `rg` serves both reads (Neo4jDeedGraph). Raises BoroughRequired or ValueError."""
    return build_comparison(resolve_text(client, graph, text, **kw), rg, rg)
