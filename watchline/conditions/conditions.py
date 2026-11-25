"""Building conditions from the records: open violations with their age and rate (Q15), and litigation cases with the respondent (Q28).

Resolution is Q1.3. Violations and cases are what was cited or brought, never findings of fault, and they are counted by class, type and status,
never summed into a score. Only a finding of After Inquest or After Trial is a harassment finding. A respondent that matches a registered owner by
name is a lead, not a finding. Rows come in as plain dicts, so the logic is tested without a graph.
"""
from dataclasses import dataclass, field
from typing import Protocol

from watchline.deeds.deeds import CAVEAT_NAME_NOT_IDENTITY, CAVEAT_OWNERS_ALL_REGISTRATIONS
from watchline.deeds.names import name_agreement
from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import (
    CAVEAT_CITED,
    CAVEAT_HARASSMENT,
    CAVEAT_LOT_WIDE,
    CAVEAT_NO_ADDRESSED,
    CAVEAT_NO_ADDRESSED_BIN,
    CAVEAT_NO_BUILDING,
    CAVEAT_NOT_IN_GRAPH,
    CAVEAT_REGISTERED_NO_BUILDING,
    CAVEAT_RELATED,
    CAVEAT_TRUNCATED,
    HARASSMENT_FINDINGS,
    MAX_BUILDINGS,
    MAX_GROUPS,
    PLUTO,
    Caveat,
    Neo4jProfileGraph,
    _match_caveats,
    _unresolved_caveat,
)
from watchline.registration.registration import Neo4jRegistrationGraph

HPD_VIOLATIONS = "HPD violations (data through 2026-07-02)"      # the snapshot dates come from specs/questions/q15.md and q28.md; the graph does not carry them
HPD_LITIGATION = "HPD litigation (data through 2026-07-09)"
HPD_REGISTRATIONS = "HPD registrations (data through 2026-05-29)"
MAX_CASES = 100
OPEN = "Open"                                                      # Violation.status values are Open and Close (probed 2026-11-25)

CAVEAT_OPEN_AT_SNAPSHOT = Caveat("open_at_snapshot", "Open means open at the data's snapshot date. Close covers closed and dismissed; finer status is not stored.")
CAVEAT_RATE = Caveat("rate_lot_wide_units",
                     ("The rate divides the open violations of every building listed for the lot by the lot's residential units (a PLUTO lot value). "
                      "The pooled figure adds the open violations of every class; the figure for each class is given beside it. It is not a severity score."))
CAVEAT_RATE_INCOMPLETE = Caveat("rate_incomplete",
                                ("More buildings are listed than this answer can read, so the open count is incomplete and no rate per unit is given."))
CAVEAT_RATE_UNAVAILABLE = Caveat("rate_unavailable", "The lot has no residential unit count, or a count of zero, so no rate per unit is given.")
CAVEAT_NO_VIOLATIONS = Caveat("no_violations_recorded", "No violation is recorded for the listed buildings. That is not a statement that conditions are good.")
CAVEAT_CASE_NOT_FAULT = Caveat("case_not_finding",
                               "A case is an action brought, not a finding of fault, unless a finding is recorded. Status and respondent are as HPD records them.")
CAVEAT_RESPONDENT_ROLE = Caveat("respondent_role_not_recorded",
                                "A respondent can be an owner, an agent or an individual; HPD does not record which. The respondent is shown as recorded.")
CAVEAT_NO_CASES = Caveat("no_cases_recorded", "No litigation case is recorded for the listed buildings. That is not a statement that none was ever brought.")
CAVEAT_DATE_ERRORS = Caveat("case_date_as_recorded", "Case dates are as recorded, including any before 1990 or after the snapshot; they are not corrected.")


class ConditionsGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def buildings(self, bbl: str) -> list[dict]: ...
    def violation_groups(self, bbl: str) -> list[dict]: ...
    def cases(self, bbl: str) -> list[dict]: ...
    def case_counts(self, bbl: str) -> list[dict]: ...
    def owners(self, bbl: str) -> list[dict]: ...


def _iso(d) -> str | None:
    return None if d is None else d.iso_format() if hasattr(d, "iso_format") else str(d)


class Neo4jConditionsGraph(Neo4jProfileGraph, Neo4jRegistrationGraph):
    """The profile and registration reads plus the condition reads. Read-only, parameterized, row-limited, with a server-side timeout."""

    def violation_groups(self, bbl: str) -> list[dict]:
        """Violations by building, class and status, with the oldest inspection date of each group."""
        rows = self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building)-[:HAS_VIOLATION]->(v:Violation) "
                          "RETURN b.bin AS bin, v.violationClass AS violationClass, v.status AS status, count(*) AS n, "
                          "min(v.inspectionDate) AS oldest ORDER BY bin, violationClass, status LIMIT $limit", bbl=bbl, limit=MAX_GROUPS)
        return [{**r, "oldest": _iso(r["oldest"])} for r in rows]

    def cases(self, bbl: str) -> list[dict]:
        """Litigation cases, newest opened first, as recorded."""
        rows = self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building)-[:HAS_LITIGATION]->(t:Litigation) "
                          "RETURN b.bin AS bin, t.litigationId AS litigationId, t.caseType AS caseType, t.caseOpenDate AS caseOpenDate, "
                          "t.caseStatus AS caseStatus, t.openJudgement AS openJudgement, t.harassmentFinding AS harassmentFinding, "
                          "t.findingDate AS findingDate, t.penalty AS penalty, t.respondent AS respondent, t.respondentKeys AS respondentKeys, "
                          "t.caseOpenDate IS NULL AS noDate ORDER BY noDate, caseOpenDate DESC, litigationId DESC LIMIT $limit", bbl=bbl, limit=MAX_CASES)
        return [{**r, "caseOpenDate": _iso(r["caseOpenDate"]), "findingDate": _iso(r["findingDate"])} for r in rows]

    def case_counts(self, bbl: str) -> list[dict]:
        """All cases of the lot's buildings by type, status and finding, so counts do not depend on the list cap."""
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(:Building)-[:HAS_LITIGATION]->(t:Litigation) "
                          "RETURN t.caseType AS caseType, t.caseStatus AS caseStatus, t.harassmentFinding AS harassmentFinding, count(*) AS n "
                          "ORDER BY caseType, caseStatus LIMIT $limit", bbl=bbl, limit=MAX_GROUPS)


# ---- violations (Q15) --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ViolationGroup:
    violationClass: str
    status: str
    n: int
    oldest: str | None              # the oldest inspection date in the group


@dataclass(frozen=True)
class BuildingViolations:
    bin: str
    address: str
    addressed: bool
    groups: tuple[ViolationGroup, ...]
    oldestOpen: str | None          # the oldest inspection date among the building's open violations


@dataclass(frozen=True)
class Rate:
    open: int                       # open violations of every listed building, pooled across classes
    units: int | None               # PLUTO residential units of the lot
    perUnit: float | None           # None when units is missing or 0, or the building list was cut
    byClass: tuple[tuple[str, int, float | None], ...] = ()   # the same by class: (class, open, per unit), so the pooled figure never stands alone
    unitsSource: str = f"{PLUTO}, lot-wide"


@dataclass(frozen=True)
class Violations:
    resolution: Answer
    lot: dict | None = None
    buildings: tuple[BuildingViolations, ...] = ()
    rate: Rate | None = None
    caveats: tuple[Caveat, ...] = field(default=())
    sources: tuple[str, ...] = ()


def _not_ready(resolution: Answer, cg: ConditionsGraph) -> tuple[list[Caveat], dict | None, list[dict], Caveat | None]:
    caveats = _match_caveats(resolution)
    unresolved = _unresolved_caveat(resolution)
    lot = cg.lot(resolution.bbl) if unresolved is None and resolution.bbl else None
    if unresolved is None and lot is None:
        unresolved = CAVEAT_NOT_IN_GRAPH.format(bbl=resolution.bbl)
    blds = cg.buildings(resolution.bbl) if unresolved is None else []
    return caveats, lot, blds, unresolved


def _building_caveats(resolution: Answer, lot: dict, blds: list[dict], caveats: list[Caveat]) -> bool:
    """Caveats about the building list. Returns False when there are no buildings, so there is nothing to read."""
    if not blds:
        caveats.append(CAVEAT_REGISTERED_NO_BUILDING if lot.get("hpdRegistered") else CAVEAT_NO_BUILDING)
        return False
    if not any(b["bin"] == resolution.bin for b in blds):
        caveats.append(CAVEAT_NO_ADDRESSED.format(bin=resolution.bin) if resolution.bin else CAVEAT_NO_ADDRESSED_BIN)
    if resolution.related_lots:
        caveats.append(CAVEAT_RELATED.format(lots=", ".join(resolution.related_lots)))
    return True


def build_violations(resolution: Answer, cg: ConditionsGraph) -> Violations:
    """Pure given the graph rows."""
    caveats, lot, blds, unresolved = _not_ready(resolution, cg)
    if unresolved:
        return Violations(resolution, caveats=(*caveats, unresolved))
    if not _building_caveats(resolution, lot, blds, caveats):
        return Violations(resolution, lot=lot, caveats=tuple(caveats), sources=(PLUTO, HPD_REGISTRATIONS))
    rows = cg.violation_groups(resolution.bbl)
    by_bin: dict[str, list[ViolationGroup]] = {}
    for r in rows:
        by_bin.setdefault(r["bin"], []).append(ViolationGroup(r["violationClass"], r["status"], r["n"], r.get("oldest")))
    buildings = tuple(BuildingViolations(
        b["bin"], b["address"], b["bin"] == resolution.bin, tuple(by_bin.get(b["bin"], ())),
        min((g.oldest for g in by_bin.get(b["bin"], ()) if g.status == OPEN and g.oldest), default=None)) for b in blds)
    n_open = sum(g.n for b in buildings for g in b.groups if g.status == OPEN)
    units = lot.get("unitsRes")
    capped = len(blds) >= MAX_BUILDINGS                       # buildings past the cap were not read, so the count and the rate are incomplete
    open_by_class: dict[str, int] = {}
    for b in buildings:
        for g in b.groups:
            if g.status == OPEN:
                open_by_class[g.violationClass] = open_by_class.get(g.violationClass, 0) + g.n
    def per(n: int) -> float | None:
        return round(n / units, 3) if units and not capped else None

    rate = Rate(n_open, units, per(n_open), tuple((k, n, per(n)) for k, n in sorted(open_by_class.items())))
    caveats += [CAVEAT_CITED, CAVEAT_OPEN_AT_SNAPSHOT, CAVEAT_LOT_WIDE,
                CAVEAT_RATE_INCOMPLETE if capped else CAVEAT_RATE if rate.perUnit is not None else CAVEAT_RATE_UNAVAILABLE]
    if capped:
        caveats.append(CAVEAT_TRUNCATED)
    if not rows:
        caveats.append(CAVEAT_NO_VIOLATIONS)
    if len(rows) >= MAX_GROUPS:
        caveats.append(CAVEAT_TRUNCATED)
    return Violations(resolution, lot=lot, buildings=buildings, rate=rate, caveats=tuple(dict.fromkeys(caveats)),
                      sources=(HPD_VIOLATIONS, PLUTO, HPD_REGISTRATIONS))


def open_violations(client, graph: Graph, cg: ConditionsGraph, text: str, **kw) -> Violations:
    """Typed address to violations by class and status, the oldest open inspection and the rate per unit."""
    return build_violations(resolve_text(client, graph, text, **kw), cg)


# ---- litigation (Q28) --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NameMatch:
    part: str                       # one part of the respondent string, as the graph keyed it
    owner: str                      # a registered owner name, as recorded
    outcome: str                    # exact_normalized or normalization_match; a lead, never proof of the same party
    rule: str | None


@dataclass(frozen=True)
class Case:
    bin: str
    litigationId: int
    caseType: str | None
    caseOpenDate: str | None
    caseStatus: str | None
    openJudgement: str | None
    harassmentFinding: str | None
    findingDate: str | None
    penalty: int | None
    respondent: str | None          # as recorded: one string, possibly several parties
    match: str                      # lead, none or not_comparable
    matches: tuple[NameMatch, ...]

    @property
    def isHarassmentFinding(self) -> bool:
        return self.harassmentFinding in HARASSMENT_FINDINGS


@dataclass(frozen=True)
class CaseCounts:
    """Cases of the lot's buildings counted by type and by status separately, and the finding values as recorded. Never one combined figure."""
    cases: int
    byType: tuple[tuple[str, int], ...]
    byStatus: tuple[tuple[str, int], ...]
    byFinding: tuple[tuple[str, int], ...]      # After Inquest, After Trial, No Harassment, and "none recorded"


@dataclass(frozen=True)
class Litigation:
    resolution: Answer
    lot: dict | None = None
    cases: tuple[Case, ...] = ()
    counts: CaseCounts | None = None
    owners: tuple[str, ...] = ()
    caveats: tuple[Caveat, ...] = field(default=())
    sources: tuple[str, ...] = ()


def _tally(rows: list[dict], key) -> tuple[tuple[str, int], ...]:
    out: dict[str, int] = {}
    for r in rows:
        out[key(r)] = out.get(key(r), 0) + r["n"]
    return tuple(sorted(out.items()))


def _matches(parts: list[str], owners: tuple[str, ...]) -> tuple[NameMatch, ...]:
    out = []
    for p in parts:
        for o in owners:
            outcome, rule = name_agreement(p, o)
            if outcome in ("exact_normalized", "normalization_match"):
                out.append(NameMatch(p, o, outcome, rule))
    return tuple(out)


def build_litigation(resolution: Answer, cg: ConditionsGraph) -> Litigation:
    """Pure given the graph rows."""
    caveats, lot, blds, unresolved = _not_ready(resolution, cg)
    if unresolved:
        return Litigation(resolution, caveats=(*caveats, unresolved))
    if not _building_caveats(resolution, lot, blds, caveats):
        return Litigation(resolution, lot=lot, caveats=tuple(caveats), sources=(HPD_REGISTRATIONS,))
    rows, grouped = cg.cases(resolution.bbl), cg.case_counts(resolution.bbl)
    owners = tuple(dict.fromkeys(o["name"] for o in cg.owners(resolution.bbl) if o.get("name")))
    cases = []
    for r in rows:
        parts = list(r.get("respondentKeys") or [])
        found = _matches(parts, owners) if parts and owners else ()
        match = "not_comparable" if not parts or not owners else "lead" if found else "none"
        cases.append(Case(r["bin"], r["litigationId"], r.get("caseType"), r.get("caseOpenDate"), r.get("caseStatus"), r.get("openJudgement"),
                          r.get("harassmentFinding"), r.get("findingDate"), r.get("penalty"), r.get("respondent"), match,
                          found))
    counts = CaseCounts(sum(g["n"] for g in grouped), _tally(grouped, lambda g: g["caseType"] or "type not recorded"),
                        _tally(grouped, lambda g: g["caseStatus"] or "status not recorded"),
                        _tally(grouped, lambda g: g["harassmentFinding"] or "none recorded"))
    if not counts.cases:
        capped = [CAVEAT_TRUNCATED] if len(blds) >= MAX_BUILDINGS else []
        return Litigation(resolution, lot=lot, counts=counts, owners=owners, caveats=tuple(dict.fromkeys([*caveats, CAVEAT_NO_CASES, *capped])),
                          sources=(HPD_LITIGATION, HPD_REGISTRATIONS))
    caveats += [CAVEAT_CITED, CAVEAT_CASE_NOT_FAULT, CAVEAT_HARASSMENT, CAVEAT_RESPONDENT_ROLE, CAVEAT_DATE_ERRORS]
    if any(c.matches for c in cases):
        caveats += [CAVEAT_NAME_NOT_IDENTITY, CAVEAT_OWNERS_ALL_REGISTRATIONS]
    if counts.cases > len(cases) or len(grouped) >= MAX_GROUPS or len(blds) >= MAX_BUILDINGS:
        caveats.append(CAVEAT_TRUNCATED)
    return Litigation(resolution, lot=lot, cases=tuple(cases), counts=counts, owners=owners, caveats=tuple(dict.fromkeys(caveats)),
                      sources=(HPD_LITIGATION, HPD_REGISTRATIONS))


def litigation_cases(client, graph: Graph, cg: ConditionsGraph, text: str, **kw) -> Litigation:
    """Typed address to the litigation cases of its buildings, the harassment findings as recorded, and respondent against owner."""
    return build_litigation(resolve_text(client, graph, text, **kw), cg)
