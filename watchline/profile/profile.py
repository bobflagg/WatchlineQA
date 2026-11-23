"""Address to building profile (Q1 plus summaries of violations, complaint problems and litigation).

Resolution is Q1.3 (watchline.geosupport.resolution). When it lands on a lot we hold, this adds the lot, every
building HPD lists for it, and per-building counts by class or type, with the caveats that apply attached.

Counts only: never summed into a severity score. Lot-wide values (units, assessed value) stay on the lot.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from neo4j import Driver, Query, RoutingControl

from watchline.geosupport.resolution import Answer, Graph, Match, resolve_text

TIMEOUT_S = 20
MAX_BUILDINGS = 200
MAX_GROUPS = 5000
HARASSMENT_FINDINGS = ("After Inquest", "After Trial")  # the only values that are a harassment finding

# Source snapshots are taken from specs/questions/q01.md (checked 2026-11-10); the graph does not carry them.
PLUTO = "PLUTO (release 26v1)"
HPD = "HPD registrations (data through 2026-05-29)"
GEOSUPPORT = "Geosupport (release 25b)"

@dataclass(frozen=True)
class Caveat:
    """A statement that travels with an answer. `code` is stable (evals and renderers key on it); `text` is for people."""
    code: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "text": self.text}


@dataclass(frozen=True)
class CaveatTemplate:
    """A caveat with blanks. `format` fills them and returns a Caveat with the same code."""
    code: str
    text: str

    def format(self, **kw) -> Caveat:
        return Caveat(self.code, self.text.format(**kw))


CAVEAT_CITED = Caveat("cited_not_fault",
                      ("Violations, complaint problems and litigation are what was cited, reported or brought, "
                      "not findings of fault. Counts are by class or type and are not a severity score."))
CAVEAT_LOT_WIDE = Caveat("lot_wide",
                         ("Residential units and assessed value are lot-wide: they belong to the lot, not to any building."))
CAVEAT_NO_BUILDING = Caveat("no_hpd_building",
                            ("No building recorded in the HPD registrations. This is not a statement that the lot has no "
                            "buildings; violations, problems and litigation exist only for HPD-registered buildings."))
CAVEAT_REGISTERED_NO_BUILDING = Caveat("registered_no_building",
                                       ("The lot is marked HPD-registered but no building is listed for it. Violations, "
                                       "problems and litigation can only be read through listed buildings, so none are shown."))
CAVEAT_COUNTS = CaveatTemplate("building_counts_differ",
                               ("Two building counts: PLUTO says {pluto}, HPD registrations list {listed}. They are different "
                               "sources and differ on many lots; neither alone is 'the number of buildings'."))
CAVEAT_PLUTO_COUNT_MISSING = CaveatTemplate("pluto_count_missing",
                                            ("PLUTO has no building count recorded for this lot; HPD registrations list {listed}."))
CAVEAT_DUPLICATES = Caveat("duplicate_flag_split",
                           ("Problem counts are split by the duplicate flag; rows flagged as duplicates are counted separately."))
CAVEAT_VARIANT = CaveatTemplate("variant_match",
                                ("The address matched by a variant of what was typed. Typed: {typed}. Returned: {returned} "
                                "(Geosupport return code {grc})."))
CAVEAT_INFERRED = CaveatTemplate("inferred_resolution",
                                 ("The lot comes from a respelled address, not the one typed: the resolution is inferred. Spellings tried: {tried}."))
CAVEAT_HOOD = CaveatTemplate("borough_inferred",
                             ("The borough was inferred from the neighborhood '{hood}', not typed."))
CAVEAT_RELATED = CaveatTemplate("related_lots_share_bin",
                                ("Other lots share the addressed building's BIN (for example a condominium): {lots}. "
                                "Building counts are not additive across these lots."))
CAVEAT_HARASSMENT = Caveat("harassment_finding_definition",
                           ("Only a finding of 'After Inquest' or 'After Trial' is a harassment finding. 'No Harassment' is a "
                           "recorded finding of none, and many cases have no finding recorded; those are not findings either way."))
CAVEAT_NO_ADDRESSED = CaveatTemplate("no_addressed_building",
                                     ("The typed address resolved to {bin}, which is not among the buildings listed for the lot, so no "
                                     "building is marked as the addressed one."))
CAVEAT_NO_ADDRESSED_BIN = Caveat("no_addressed_bin",
                                 ("Geosupport returned no building (BIN) for this address, so no building is marked as addressed."))
CAVEAT_TRUNCATED = Caveat("truncated",
                          ("Results were truncated at a row limit; counts may be incomplete."))

CAVEAT_AMBIGUOUS = Caveat("ambiguous_street",
                          ("The street is ambiguous. Similar street names are listed as candidates; no lot was chosen."))
CAVEAT_NOT_FOUND = CaveatTemplate("not_found",
                                  ("No lot found (Geosupport return code {grc}). Spellings tried: {tried}. No nearby lot was guessed."))
CAVEAT_UNAVAILABLE = Caveat("geosupport_unavailable",
                            ("Geosupport could not be reached. This is an outage, not an answer about the address."))
CAVEAT_NOT_IN_GRAPH = CaveatTemplate("not_in_graph",
                                     ("Geosupport returned BBL {bbl}, but the graph holds no such lot, so no buildings, violations, "
                                     "problems or litigation could be read. This does not mean the lot has none."))


class ProfileGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def buildings(self, bbl: str) -> list[dict]: ...
    def violations(self, bbl: str) -> list[dict]: ...
    def problems(self, bbl: str) -> list[dict]: ...
    def litigation(self, bbl: str) -> list[dict]: ...


class Neo4jProfileGraph:
    """Read-only, parameterized, row-limited, with a server-side timeout. No free-form Cypher from callers."""

    def __init__(self, driver: Driver, database: str):
        self._driver, self._db = driver, database

    def _read(self, text: str, **params) -> list[dict]:
        records = self._driver.execute_query(Query(text, timeout=TIMEOUT_S), params, database_=self._db,
                                             routing_=RoutingControl.READ).records
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
class Characteristic:
    name: str
    value: object
    source: str            # where the value comes from, with its snapshot


@dataclass(frozen=True)
class Count:
    name: str
    value: int | None
    unit: str              # what is being counted
    source: str


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
    characteristics: tuple[Characteristic, ...] = ()
    counts: tuple[Count, ...] = ()                  # parcels, buildings (two sources) and units, never merged
    buildings_listed: int | None = None             # BINs HPD lists (not PLUTO's count)
    buildings: tuple[BuildingSummary, ...] = ()
    caveats: tuple[Caveat, ...] = field(default=())

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


def _match_caveats(res: Answer) -> list[Caveat]:
    out = []
    same_as_typed = " ".join((res.returned or "").upper().split()) == " ".join(res.input.upper().split())
    if res.outcome is Match.VARIANT and not (res.borough_inferred_from and same_as_typed and not res.inferred):
        out.append(CAVEAT_VARIANT.format(typed=res.input, returned=res.returned or "not reported", grc=res.grc))
    if res.inferred:
        out.append(CAVEAT_INFERRED.format(tried=", ".join(res.tried) or "none"))
    if res.borough_inferred_from:
        out.append(CAVEAT_HOOD.format(hood=res.borough_inferred_from))
    return out


def _unresolved_caveat(res: Answer) -> Caveat | None:
    match res.outcome:
        case Match.AMBIGUOUS:
            return CAVEAT_AMBIGUOUS
        case Match.NOT_FOUND:
            return CAVEAT_NOT_FOUND.format(grc=res.grc, tried=", ".join(res.tried) or "none")
        case Match.UNAVAILABLE:
            return CAVEAT_UNAVAILABLE
    return CAVEAT_NOT_IN_GRAPH.format(bbl=res.bbl) if res.bbl and not res.in_graph else None


def build_profile(resolution: Answer, pg: ProfileGraph) -> Profile:
    """Pure given the graph rows. The resolution decides whether there is anything to profile."""
    caveats = _match_caveats(resolution)
    unresolved = _unresolved_caveat(resolution)
    lot = pg.lot(resolution.bbl) if unresolved is None and resolution.bbl else None
    if unresolved is None and lot is None:
        unresolved = CAVEAT_NOT_IN_GRAPH.format(bbl=resolution.bbl)
    if unresolved:
        return Profile(resolution, caveats=(*caveats, unresolved))

    blds = pg.buildings(resolution.bbl)
    viol_rows, prob_rows, lit_rows = (pg.violations(resolution.bbl), pg.problems(resolution.bbl),
                                      pg.litigation(resolution.bbl))
    viol = _group(viol_rows, lambda r: (r["violationClass"], r["status"]))
    prob = _group(prob_rows, lambda r: (r["majorCategory"], bool(r["duplicate"])))
    lit = _group(lit_rows, lambda r: (r["caseType"], r["caseStatus"]))
    harass: Counter = Counter()
    for r in lit_rows:
        if r["harassmentFinding"] in HARASSMENT_FINDINGS:
            harass[r["bin"]] += r["n"]

    summaries = tuple(BuildingSummary(
        bin=b["bin"], address=b["address"], addressed=b["bin"] == resolution.bin,
        violations=dict(viol.get(b["bin"], {})), problems=dict(prob.get(b["bin"], {})),
        litigation=dict(lit.get(b["bin"], {})), harassment_findings=harass.get(b["bin"], 0)) for b in blds)

    characteristics = (
        Characteristic("yearBuilt", lot["yearBuilt"], PLUTO),
        Characteristic("buildingClass", lot["buildingClass"], PLUTO),
        Characteristic("unitsRes", lot["unitsRes"], f"{PLUTO}, lot-wide"),
        Characteristic("assessedTotal", lot["assessedTotal"], f"{PLUTO}, lot-wide, whole dollars"),
    )
    counts = (
        Count("parcels", 1, "tax lot (BBL) the address resolved to", GEOSUPPORT),
        Count("buildings (PLUTO)", lot["plutoNumBuildings"], "buildings as counted by PLUTO", PLUTO),
        Count("buildings (HPD)", len(blds), "BINs listed in HPD registrations", HPD),
        Count("residential units", lot["unitsRes"], "residential units, lot-wide", PLUTO),
    )

    caveats += [CAVEAT_CITED, CAVEAT_LOT_WIDE]
    pluto_n = lot["plutoNumBuildings"]
    if not blds:
        caveats.append(CAVEAT_REGISTERED_NO_BUILDING if lot.get("hpdRegistered") else CAVEAT_NO_BUILDING)
    elif pluto_n is None:
        caveats.append(CAVEAT_PLUTO_COUNT_MISSING.format(listed=len(blds)))
    elif pluto_n != len(blds):
        caveats.append(CAVEAT_COUNTS.format(pluto=pluto_n, listed=len(blds)))
    if blds and not any(s.addressed for s in summaries):
        caveats.append(CAVEAT_NO_ADDRESSED.format(bin=resolution.bin) if resolution.bin else CAVEAT_NO_ADDRESSED_BIN)
    if any(d for s in summaries for (_, d) in s.problems):
        caveats.append(CAVEAT_DUPLICATES)
    if any(s.litigation for s in summaries):
        caveats.append(CAVEAT_HARASSMENT)
    if resolution.related_lots:
        caveats.append(CAVEAT_RELATED.format(lots=", ".join(resolution.related_lots)))
    if len(blds) >= MAX_BUILDINGS or max(len(viol_rows), len(prob_rows), len(lit_rows)) >= MAX_GROUPS:
        caveats.append(CAVEAT_TRUNCATED)
    return Profile(resolution, lot=lot, characteristics=characteristics, counts=counts, buildings_listed=len(blds),
                   buildings=summaries, caveats=tuple(caveats))


def building_profile(client, graph: Graph, pg: ProfileGraph, text: str, **kw) -> Profile:
    """Typed address to profile. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_profile(resolve_text(client, graph, text, **kw), pg)
