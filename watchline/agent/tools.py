"""Agent tools. The model sees only what these return, so every failure is an answer, never an exception.

`building_profile` wraps watchline.profile: read-only (Neo4jProfileGraph), row-limited and timed out at the graph,
and capped again here so a lot with hundreds of buildings cannot flood the model's context.
"""
from typing import Any

import httpx
from langchain.tools import tool
from neo4j.exceptions import DriverError, Neo4jError

from watchline.geosupport.resolution import BoroughRequired, Graph
from watchline.profile.profile import Profile, ProfileGraph, building_profile

MAX_BUILDINGS_OUT = 25
CAVEAT_BUILDINGS_CAPPED = "Showing {shown} of {total} buildings listed for the lot; the rest are omitted from this output."


def _rows(counts: dict, names: tuple[str, ...]) -> list[dict]:
    return [{**dict(zip(names, key if isinstance(key, tuple) else (key,))), "n": n} for key, n in sorted(counts.items(), key=str)]


VIOLATION_KEYS = ("violationClass", "status")
PROBLEM_KEYS = ("majorCategory", "duplicate")
LITIGATION_KEYS = ("caseType", "caseStatus")


def profile_to_dict(p: Profile, max_buildings: int = MAX_BUILDINGS_OUT) -> dict[str, Any]:
    """JSON-safe view of a Profile. Counts stay by class or type; nothing is summed into a total or score."""
    r = p.resolution
    out: dict[str, Any] = {
        "status": "ok",
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
        "buildings": [],
        "lot_totals": {},
        "caveats": list(p.caveats),
    }
    if p.lot is None:
        return out
    shown = sorted(p.buildings, key=lambda b: not b.addressed)[:max_buildings]   # the addressed building always shows
    out["buildings"] = [{
        "bin": b.bin, "address": b.address, "addressed": b.addressed,
        "violations": _rows(b.violations, VIOLATION_KEYS), "problems": _rows(b.problems, PROBLEM_KEYS),
        "litigation": _rows(b.litigation, LITIGATION_KEYS), "harassment_findings": b.harassment_findings,
    } for b in shown]
    totals = p.lot_totals()
    out["lot_totals"] = {"violations": _rows(totals["violations"], VIOLATION_KEYS),
                         "problems": _rows(totals["problems"], PROBLEM_KEYS),
                         "litigation": _rows(totals["litigation"], LITIGATION_KEYS)}
    if len(p.buildings) > len(shown):
        out["caveats"].append(CAVEAT_BUILDINGS_CAPPED.format(shown=len(shown), total=len(p.buildings)))
    return out


def make_building_profile_tool(client, graph: Graph, pg: ProfileGraph):
    """Bind the profile lookup to its clients. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def building_profile_tool(address: str, borough: str | None = None, zip_code: str | None = None) -> dict:
        """Look up a New York City street address: its tax lot (BBL), the buildings (BIN) HPD lists for it, lot
        characteristics, and counts of violations, complaint problems and litigation per building, with caveats.

        Call this first for any question that starts from a street address. The result is source-reported data:
        violations, problems and litigation are what was cited, reported or brought, not findings of fault. Always
        pass the returned caveats on to the user. If status is needs_borough, ask the user for the borough or ZIP.

        Args:
            address: House number and street as the user typed it, optionally with borough or ZIP.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            p = building_profile(client, graph, pg, address, borough=borough, zip5=zip_code)
        except BoroughRequired as e:
            return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
        except ValueError as e:
            return {"status": "invalid_input", "message": str(e)}
        except (Neo4jError, DriverError, httpx.HTTPError) as e:
            return {"status": "error", "message": f"The lookup failed ({type(e).__name__}). This is an outage, "
                                                  "not an answer about the address; do not guess."}
        return profile_to_dict(p)

    building_profile_tool.name = "building_profile"
    return building_profile_tool
