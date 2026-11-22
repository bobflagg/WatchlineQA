"""Address to building profile (Q1 plus summaries of violations, complaint problems and litigation).

Resolution is Q1.3 (watchline.geosupport.resolution). When it lands on a lot we hold, this adds the lot, every
building HPD lists for it, and per-building counts by class or type, with the caveats that apply attached.

Counts only: never summed into a severity score. Lot-wide values (units, assessed value) stay on the lot.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from neo4j import Driver, RoutingControl

from watchline.geosupport.resolution import Answer, Graph, Match, resolve_text

TIMEOUT_S = 20
MAX_BUILDINGS = 200
MAX_GROUPS = 5000
HARASSMENT_FINDINGS = ("After Inquest", "After Trial")  # the only values that are a harassment finding

CAVEAT_CITED = ("Violations, complaint problems and litigation are what was cited, reported or brought, "
                "not findings of fault. Counts are by class or type and are not a severity score.")
CAVEAT_LOT_WIDE = "Residential units and assessed value are lot-wide: they belong to the lot, not to any building."
CAVEAT_UNREGISTERED = ("No building recorded in the HPD registrations. This is not a statement that the lot "
                       "has no buildings; violations, problems and litigation exist only for HPD-registered buildings.")
CAVEAT_COUNTS = ("Two building counts: PLUTO says {pluto}, HPD registrations list {listed}. They are different "
                 "sources and differ on many lots; neither alone is 'the number of buildings'.")
CAVEAT_DUPLICATES = "Problem counts include rows flagged as duplicates; they are counted separately."
CAVEAT_VARIANT = "The address matched by a variant of what was typed (returned address: {returned})."
CAVEAT_HOOD = "The borough was inferred from the neighborhood '{hood}', not typed."
CAVEAT_RELATED = "Other lots share the addressed building's BIN (for example a condominium): {lots}."
CAVEAT_HARASSMENT = ("Only a finding of 'After Inquest' or 'After Trial' is a harassment finding; other cases "
                     "were brought, not found.")


class ProfileGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def buildings(self, bbl: str) -> list[dict]: ...
    def violations(self, bbl: str) -> list[dict]: ...
    def problems(self, bbl: str) -> list[dict]: ...
    def litigation(self, bbl: str) -> list[dict]: ...


class Neo4jProfileGraph:
    """Read-only, parameterized, row-limited, with a timeout. No free-form Cypher from callers."""

    def __init__(self, driver: Driver, database: str):
        self._driver, self._db = driver, database

    def _read(self, query: str, **params) -> list[dict]:
        records = self._driver.execute_query(query, params, database_=self._db, routing_=RoutingControl.READ,
                                             timeout=TIMEOUT_S).records
        return [r.data() for r in records]

    def lot(self, bbl: str) -> dict | None:
        rows = self._read("CYPHER 25 MATCH (l:Lot {bbl: $bbl}) "
                          "RETURN l.bbl AS bbl, l.address AS address, l.yearBuilt AS yearBuilt, "
                          "l.buildingClass AS buildingClass, l.unitsRes AS unitsRes, l.assessedTotal AS assessedTotal, "
                          "l.plutoNumBuildings AS plutoNumBuildings, l.hpdRegistered AS hpdRegistered", bbl=bbl)
        return rows[0] if rows else None

    def buildings(self, bbl: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building) "
                          "RETURN b.bin AS bin, b.address AS address ORDER BY bin LIMIT $limit",
                          bbl=bbl, limit=MAX_BUILDINGS)

    def violations(self, bbl: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building)-[:HAS_VIOLATION]->(v:Violation) "
                          "RETURN b.bin AS bin, v.violationClass AS violationClass, v.status AS status, count(*) AS n "
                          "LIMIT $limit", bbl=bbl, limit=MAX_GROUPS)

    def problems(self, bbl: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building)-[:HAS_PROBLEM]->(p:Problem) "
                          "RETURN b.bin AS bin, p.majorCategory AS majorCategory, p.duplicate AS duplicate, count(*) AS n "
                          "LIMIT $limit", bbl=bbl, limit=MAX_GROUPS)

    def litigation(self, bbl: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building)-[:HAS_LITIGATION]->(t:Litigation) "
                          "RETURN b.bin AS bin, t.caseType AS caseType, t.caseStatus AS caseStatus, "
                          "t.harassmentFinding AS harassmentFinding, count(*) AS n LIMIT $limit",
                          bbl=bbl, limit=MAX_GROUPS)


@dataclass(frozen=True)
class BuildingSummary:
    bin: str
    address: str
    addressed: bool                                 # the building the typed address resolved to
    violations: dict[tuple[str, str], int]          # (class, status) -> count
    problems: dict[tuple[str, bool], int]           # (major category, duplicate) -> count
    litigation: dict[tuple[str, str], int]          # (case type, case status) -> count
    harassment_findings: int                        # cases with "After Inquest" or "After Trial"


@dataclass(frozen=True)
class Profile:
    resolution: Answer
    lot: dict | None = None                         # lot-wide values, as recorded
    buildings_listed: int | None = None             # BINs HPD lists (not PLUTO's count)
    buildings: tuple[BuildingSummary, ...] = ()
    caveats: tuple[str, ...] = field(default=())

    def lot_totals(self) -> dict[str, dict]:
        """Same-type sums across buildings. Counts by class or type only, never one combined number."""
        out: dict[str, Counter] = {"violations": Counter(), "problems": Counter(), "litigation": Counter()}
        for b in self.buildings:
            out["violations"].update(b.violations)
            out["problems"].update(b.problems)
            out["litigation"].update(b.litigation)
        return {k: dict(v) for k, v in out.items()}


def _group(rows: list[dict], key) -> dict[str, Counter]:
    by_bin: dict[str, Counter] = {}
    for r in rows:
        by_bin.setdefault(r["bin"], Counter())[key(r)] += r["n"]
    return by_bin


def build_profile(resolution: Answer, pg: ProfileGraph) -> Profile:
    """Pure given the graph rows. The resolution decides whether there is anything to profile."""
    caveats: list[str] = []
    if resolution.outcome is Match.VARIANT and not resolution.borough_inferred_from:
        caveats.append(CAVEAT_VARIANT.format(returned=resolution.tried[-1] if resolution.tried else resolution.input))
    if resolution.borough_inferred_from:
        caveats.append(CAVEAT_HOOD.format(hood=resolution.borough_inferred_from))
    if resolution.outcome not in (Match.EXACT, Match.VARIANT) or not resolution.bbl or not resolution.in_graph:
        return Profile(resolution, caveats=tuple(caveats))

    lot = pg.lot(resolution.bbl)
    if lot is None:
        return Profile(resolution, caveats=tuple(caveats))
    blds = pg.buildings(resolution.bbl)
    viol = _group(pg.violations(resolution.bbl), lambda r: (r["violationClass"], r["status"]))
    prob = _group(pg.problems(resolution.bbl), lambda r: (r["majorCategory"], bool(r["duplicate"])))
    lit_rows = pg.litigation(resolution.bbl)
    lit = _group(lit_rows, lambda r: (r["caseType"], r["caseStatus"]))
    harass: Counter = Counter()
    for r in lit_rows:
        if r["harassmentFinding"] in HARASSMENT_FINDINGS:
            harass[r["bin"]] += r["n"]

    summaries = tuple(BuildingSummary(
        bin=b["bin"], address=b["address"], addressed=b["bin"] == resolution.bin,
        violations=dict(viol.get(b["bin"], {})), problems=dict(prob.get(b["bin"], {})),
        litigation=dict(lit.get(b["bin"], {})), harassment_findings=harass.get(b["bin"], 0)) for b in blds)

    caveats += [CAVEAT_CITED, CAVEAT_LOT_WIDE]
    if not blds:
        caveats.append(CAVEAT_UNREGISTERED)
    if lot["plutoNumBuildings"] != len(blds):
        caveats.append(CAVEAT_COUNTS.format(pluto=lot["plutoNumBuildings"], listed=len(blds)))
    if any(d for s in summaries for (_, d) in s.problems):
        caveats.append(CAVEAT_DUPLICATES)
    if any(s.litigation for s in summaries):
        caveats.append(CAVEAT_HARASSMENT)
    if resolution.related_lots:
        caveats.append(CAVEAT_RELATED.format(lots=", ".join(resolution.related_lots)))
    return Profile(resolution, lot=lot, buildings_listed=len(blds), buildings=summaries, caveats=tuple(caveats))


def building_profile(client, graph: Graph, pg: ProfileGraph, text: str, **kw) -> Profile:
    """Typed address to profile. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_profile(resolve_text(client, graph, text, **kw), pg)
