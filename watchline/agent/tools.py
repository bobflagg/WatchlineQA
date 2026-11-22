"""Agent tools. The model sees only what these return, so every failure is an answer, never an exception
(a catch-all returns status "error" and names only the exception type).

`building_profile` wraps watchline.profile: read-only (Neo4jProfileGraph), row-limited and timed out at the graph,
and capped again here so a lot with hundreds of buildings cannot flood the model's context.
"""
from typing import Any

from langchain.tools import tool

from watchline.geosupport.resolution import BoroughRequired, Graph, Match
from watchline.profile.profile import MAX_BUILDINGS, Profile, ProfileGraph, building_profile

MAX_BUILDINGS_OUT = 25
CAVEAT_BUILDINGS_CAPPED = ("Showing {shown} of {total} buildings listed for the lot; the rest are omitted from this output. "
                           "'totals_across_all_listed_buildings' still covers all {total}, so it will not equal the sum of the rows shown.")
ERROR_MESSAGE = ("The lookup failed ({kind}). This is an outage or a fault, not an answer about the address; "
                 "do not guess.")


def _rows(counts: dict, names: tuple[str, ...]) -> list[dict]:
    return [{**dict(zip(names, key if isinstance(key, tuple) else (key,))), "n": n} for key, n in sorted(counts.items(), key=str)]


VIOLATION_KEYS = ("violationClass", "status")
PROBLEM_KEYS = ("majorCategory", "duplicate")
LITIGATION_KEYS = ("caseType", "caseStatus")


def profile_to_dict(p: Profile, max_buildings: int = MAX_BUILDINGS_OUT) -> dict[str, Any]:
    """JSON-safe view of a Profile. Counts stay by class or type; nothing is summed into a total or score."""
    r = p.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",   # an outage is never an answer about the address
        "resolution": {
            "input": r.input, "outcome": str(r.outcome), "bbl": r.bbl, "bin": r.bin, "in_graph": r.in_graph,
            "related_lots": list(r.related_lots), "candidates": list(r.candidates), "grc": r.grc,
            "tried": list(r.tried), "returned": r.returned, "inferred": r.inferred,
            "borough_inferred_from": r.borough_inferred_from,
        },
        "lot": p.lot,
        "characteristics": [{"name": c.name, "value": c.value, "source": c.source} for c in p.characteristics],
        "counts": [{"name": c.name, "value": c.value, "unit": c.unit, "source": c.source} for c in p.counts],
        "buildings_listed": p.buildings_listed,
        "buildings_listed_is_lower_bound": (p.buildings_listed or 0) >= MAX_BUILDINGS,   # the graph read stopped at its row limit
        "buildings": [],
        "totals_across_all_listed_buildings": {},
        "caveats": list(p.caveats),
    }
    if p.lot is None:
        return out
    shown = sorted(p.buildings, key=lambda b: not b.addressed)[:max_buildings]   # the addressed building always shows
    out["buildings"] = [{
        "bin": b.bin, "address": b.address, "addressed": b.addressed,
        "violations": _rows(b.violations, VIOLATION_KEYS), "problems": _rows(b.problems, PROBLEM_KEYS),
        "litigation": _rows(b.litigation, LITIGATION_KEYS),
        "harassment_findings_after_inquest_or_trial": b.harassment_findings,
    } for b in shown]
    totals = p.lot_totals()
    out["totals_across_all_listed_buildings"] = {"violations": _rows(totals["violations"], VIOLATION_KEYS),
                                         "problems": _rows(totals["problems"], PROBLEM_KEYS),
                                         "litigation": _rows(totals["litigation"], LITIGATION_KEYS)}
    if len(p.buildings) > len(shown):
        out["caveats"].append(CAVEAT_BUILDINGS_CAPPED.format(shown=len(shown), total=len(p.buildings)))
    return out


def make_building_profile_tool(client, graph: Graph, pg: ProfileGraph):
    """Bind the profile lookup to its clients. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def building_profile_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """Look up a New York City street address: its tax lot (BBL), the buildings (BIN) HPD lists for it, lot
        characteristics, and counts of violations, complaint problems and litigation per building, with caveats.

        Call this first for any question that starts from a street address. The result is source-reported data:
        violations, problems and litigation are what was cited, reported or brought, not findings of fault. Always
        pass the returned caveats on to the user. Check status first: ok means a lookup was made (read
        resolution.outcome for exact, variant, ambiguous or not_found); needs_borough means ask the user for the
        borough or ZIP; invalid_input means the text was not an address; error means an outage or fault, not an
        answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                p = building_profile(client, graph, pg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:   # only resolve_text raises this: text without a house number and street, or a conflict
                return {"status": "invalid_input", "message": str(e)}
            return profile_to_dict(p)
        except Exception as e:  # noqa: BLE001  outages, ReleaseMismatch, bad rows: the model gets an answer, never a stack trace
            return {"status": "error", "message": ERROR_MESSAGE.format(kind=type(e).__name__)}

    building_profile_tool.name = "building_profile"
    return building_profile_tool
