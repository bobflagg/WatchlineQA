"""Address to the deed timeline of the lot: every recorded deed with its dates, amount, grantors and grantees (Q12.1).

Resolution is Q1.3. Deeds are listed newest first by recorded date, with the party names exactly as recorded (variants of one name are
separate strings, never merged). The counts come from a separate grouped read, so they cover every deed in the period even when the
list is capped. A deed is counted as "not a sale" when its amount is 0 or its type is a correction or confirmatory deed (CORRD, CONDEED);
the answer never calls any deed a sale of the building. Nothing is attributed to a current owner (that is Q12.3, not built).
"""
from dataclasses import dataclass, field
from typing import Protocol

from watchline.conditions.conditions import Neo4jConditionsGraph
from watchline.contacts.contacts import Neo4jContactGraph
from watchline.deeds.deeds import ACRIS, CAVEAT_MULTI_LOT, CAVEAT_NO_DEED, CAVEAT_NOT_SALE, DEED_TYPES, Neo4jDeedGraph
from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import (
    CAVEAT_NOT_IN_GRAPH,
    CAVEAT_TRUNCATED,
    MAX_GROUPS,
    Caveat,
    _match_caveats,
    _unresolved_caveat,
)
from watchline.registration.registration import RegistrationGraph, _iso

MAX_DEEDS = 50                    # newest deeds returned from the graph; the counts still cover all of them
MAX_NAMES = 10                    # party names returned per deed and side; the row totals still cover all of them
NOT_SALE_TYPES = ("CORRD", "CONDEED")

CAVEAT_ORDER = Caveat("timeline_by_recorded",
                      "Deeds are ordered by recorded date, newest first, not by the date written on the deed.")
CAVEAT_CORRECTION = Caveat("deed_correction_type",
                           "At least one deed is a correction or confirmatory deed (CORRD or CONDEED). It is not a sale and is counted as not a sale.")
CAVEAT_PARTY_NAMES = Caveat("party_names_as_recorded",
                            ("Grantor and grantee names are shown exactly as recorded. Spelling variants are separate strings and are "
                             "not merged. The same name on both sides is kept. A name is not a finding about who holds or held title."))
CAVEAT_PERIOD = Caveat("period_bounds",
                       "Only deeds recorded inside the stated period (inclusive) are listed and counted.")


@dataclass(frozen=True)
class TimelineDeed:
    documentId: str
    docType: str
    docDate: str | None             # the date written on the deed; absent when ACRIS has none
    recordedDate: str
    amount: int | None              # as recorded; 0 is not a free sale
    otherLots: int                  # how many other graph lots the deed names
    grantors: tuple[str, ...]       # up to MAX_NAMES distinct names, as recorded
    grantorRows: int                # grantor party rows recorded on the deed
    grantees: tuple[str, ...]
    granteeRows: int

    @property
    def notSale(self) -> bool:
        return self.amount == 0 or self.docType in NOT_SALE_TYPES


@dataclass(frozen=True)
class Counts:
    """Deeds in the period, counted as deeds. `by_type` and the not-a-sale numbers are separate counts, never netted."""
    deeds: int
    notSale: int
    amountZero: int
    byType: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class DeedTimeline:
    resolution: Answer
    lot: dict | None = None
    deeds: tuple[TimelineDeed, ...] = ()
    counts: Counts | None = None
    since: str | None = None
    until: str | None = None
    caveats: tuple[Caveat, ...] = field(default=())
    sources: tuple[str, ...] = ()


class TimelineGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def timeline(self, bbl: str, since: str | None, until: str | None) -> list[dict]: ...
    def deed_counts(self, bbl: str, since: str | None, until: str | None) -> list[dict]: ...


_IN_PERIOD = ("(:Lot {bbl: $bbl})-[:HAS_DEED]->(d:Deed WHERE d.docType IN $types "
              "AND ($since IS NULL OR d.recordedDate >= date($since)) AND ($until IS NULL OR d.recordedDate <= date($until)))")


class Neo4jTimelineGraph(Neo4jDeedGraph, Neo4jContactGraph, Neo4jConditionsGraph):
    """The registration, latest-deed, contact and condition reads plus the timeline reads, so one object serves every tool. Read-only, parameterized, row-limited, with a server-side timeout. No free-form Cypher from callers."""

    def timeline(self, bbl: str, since: str | None, until: str | None) -> list[dict]:
        """One row per deed, newest recorded first, with up to MAX_NAMES distinct names per side and the party row totals."""
        rows = self._read(f"CYPHER 25 MATCH {_IN_PERIOD} "
                          "RETURN d.documentId AS documentId, d.docType AS docType, d.docDate AS docDate, "
                          "d.recordedDate AS recordedDate, d.amount AS amount, COUNT { (d)<-[:HAS_DEED]-(:Lot) } - 1 AS otherLots, "
                          "COLLECT { MATCH (d)-[:HAS_GRANTOR]->(g:Grantor) WHERE g.name IS NOT NULL "
                          "RETURN DISTINCT g.name AS n ORDER BY n LIMIT $names } AS grantors, "
                          "COUNT { (d)-[:HAS_GRANTOR]->(:Grantor) } AS grantorRows, "
                          "COLLECT { MATCH (d)-[:HAS_GRANTEE]->(g:Grantee) WHERE g.name IS NOT NULL "
                          "RETURN DISTINCT g.name AS n ORDER BY n LIMIT $names } AS grantees, "
                          "COUNT { (d)-[:HAS_GRANTEE]->(:Grantee) } AS granteeRows "
                          "ORDER BY recordedDate DESC, documentId LIMIT $limit",
                          bbl=bbl, types=list(DEED_TYPES), since=since, until=until, names=MAX_NAMES, limit=MAX_DEEDS)
        return [{**r, "docDate": _iso(r["docDate"]), "recordedDate": _iso(r["recordedDate"])} for r in rows]

    def deed_counts(self, bbl: str, since: str | None, until: str | None) -> list[dict]:
        """Deeds in the period grouped by type and whether the amount is 0, so counts do not depend on the list cap."""
        return self._read(f"CYPHER 25 MATCH {_IN_PERIOD} RETURN d.docType AS docType, coalesce(d.amount = 0, false) AS zero, count(*) AS n "
                          "ORDER BY docType, zero LIMIT $limit",
                          bbl=bbl, types=list(DEED_TYPES), since=since, until=until, limit=MAX_GROUPS)


def _counts(rows: list[dict]) -> Counts:
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["docType"]] = by_type.get(r["docType"], 0) + r["n"]
    return Counts(deeds=sum(r["n"] for r in rows),
                  notSale=sum(r["n"] for r in rows if r["zero"] or r["docType"] in NOT_SALE_TYPES),
                  amountZero=sum(r["n"] for r in rows if r["zero"]),
                  byType=tuple(sorted(by_type.items())))


def build_timeline(resolution: Answer, tg: TimelineGraph, since: str | None = None, until: str | None = None) -> DeedTimeline:
    """Pure given the graph rows. The resolution decides whether there is anything to read."""
    caveats = _match_caveats(resolution)
    unresolved = _unresolved_caveat(resolution)
    lot = tg.lot(resolution.bbl) if unresolved is None and resolution.bbl else None
    if unresolved is None and lot is None:
        unresolved = CAVEAT_NOT_IN_GRAPH.format(bbl=resolution.bbl)
    if unresolved:
        return DeedTimeline(resolution, since=since, until=until, caveats=(*caveats, unresolved))

    rows = tg.timeline(resolution.bbl, since, until)
    counts = _counts(tg.deed_counts(resolution.bbl, since, until))
    deeds = tuple(TimelineDeed(r["documentId"], r["docType"], r.get("docDate") or None, r["recordedDate"], r.get("amount"),
                               max(r.get("otherLots") or 0, 0), tuple(r.get("grantors") or ()), r.get("grantorRows") or 0,
                               tuple(r.get("grantees") or ()), r.get("granteeRows") or 0) for r in rows)
    if since or until:
        caveats.append(CAVEAT_PERIOD)
    if not deeds:
        return DeedTimeline(resolution, lot=lot, counts=counts, since=since, until=until,
                            caveats=(*caveats, CAVEAT_NO_DEED), sources=(ACRIS,))
    caveats += [CAVEAT_ORDER, CAVEAT_PARTY_NAMES]
    if counts.notSale:
        caveats.append(CAVEAT_NOT_SALE)
    if any(d.docType in NOT_SALE_TYPES for d in deeds):
        caveats.append(CAVEAT_CORRECTION)
    if any(d.otherLots for d in deeds):
        caveats.append(CAVEAT_MULTI_LOT)
    if counts.deeds > len(deeds):
        caveats.append(CAVEAT_TRUNCATED)
    return DeedTimeline(resolution, lot=lot, deeds=deeds, counts=counts, since=since, until=until,
                        caveats=tuple(dict.fromkeys(caveats)), sources=(ACRIS,))


def deed_timeline(client, graph: Graph, tg: RegistrationGraph | TimelineGraph, text: str,
                  since: str | None = None, until: str | None = None, **kw) -> DeedTimeline:
    """Typed address to the deed timeline. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_timeline(resolve_text(client, graph, text, **kw), tg, since, until)
