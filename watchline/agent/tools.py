"""Agent tools. The model sees only what these return, so every failure is an answer, never an exception
(a catch-all returns status "error" and names only the exception type).

`building_profile` wraps watchline.profile: read-only (Neo4jProfileGraph), row-limited and timed out at the graph,
and capped again here so a lot with hundreds of buildings cannot flood the model's context.
`registered_owner` wraps watchline.registration the same way (Q2: HPD registrations and their owner contacts).
`deed_vs_owner` wraps watchline.deeds (Q3: the most recent deed(s), their grantees, and name and address agreement with the HPD owners).
"""
from typing import Any

from langchain.tools import tool

from watchline.deeds.deeds import DeedComparison, deed_vs_owner
from watchline.geosupport.resolution import BoroughRequired, Graph, Match
from watchline.profile.profile import (
    GEOSUPPORT,
    HPD,
    MAX_BUILDINGS,
    PLUTO,
    CaveatTemplate,
    Profile,
    ProfileGraph,
    building_profile,
)
from watchline.registration.registration import RegistrationGraph, Registrations, registered_owners

MAX_BUILDINGS_OUT = 25
CAVEAT_BUILDINGS_CAPPED = CaveatTemplate("buildings_capped",
                                         ("Showing {shown} of {total} buildings listed for the lot; the rest are omitted from this output. "
                                         "'totals_across_all_listed_buildings' still covers all {total}, so it will not equal the sum of the rows shown."))
CAVEAT_REGISTRATION_BUILDINGS_CAPPED = CaveatTemplate("buildings_capped",
                                                     "Showing {shown} of {total} buildings listed for the lot; the rest are omitted from this output.")
ADDRESS_KEYS = ("mailingAddress", "addressLine2", "zip")   # the second line is reported apart from the match
MAX_DEEDS_OUT = 10
MAX_PAIRS_OUT = 100
CAVEAT_DEEDS_CAPPED = CaveatTemplate("deeds_capped", "Showing {shown} of {total} deeds recorded on the latest date; the rest are omitted from this output.")
CAVEAT_COMPARISON_CAPPED = CaveatTemplate("comparison_capped",
                                          "Showing {shown} of {total} grantee and owner comparisons; the rest are omitted from this output.")
ERROR_CAVEAT = CaveatTemplate("lookup_failed", "The lookup failed ({kind}). This is an outage or a fault, not an answer about the address; "
                              "do not guess.")


def _rows(counts: dict, names: tuple[str, ...]) -> list[dict]:
    return [{**dict(zip(names, key if isinstance(key, tuple) else (key,))), "n": n} for key, n in sorted(counts.items(), key=str)]


VIOLATION_KEYS = ("violationClass", "status")
PROBLEM_KEYS = ("majorCategory", "duplicate")
LITIGATION_KEYS = ("caseType", "caseStatus")


def _resolution_dict(r) -> dict[str, Any]:
    return {
        "input": r.input, "outcome": str(r.outcome), "bbl": r.bbl, "bin": r.bin, "in_graph": r.in_graph,
        "related_lots": list(r.related_lots), "candidates": list(r.candidates), "grc": r.grc,
        "tried": list(r.tried), "returned": r.returned, "inferred": r.inferred,
        "borough_inferred_from": r.borough_inferred_from,
    }


def profile_to_dict(p: Profile, max_buildings: int = MAX_BUILDINGS_OUT) -> dict[str, Any]:
    """JSON-safe view of a Profile. Counts stay by class or type; nothing is summed into a total or score."""
    r = p.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",   # an outage is never an answer about the address
        "resolution": _resolution_dict(r),
        "lot": p.lot,
        "characteristics": [{"name": c.name, "value": c.value, "source": c.source} for c in p.characteristics],
        "counts": [{"name": c.name, "value": c.value, "unit": c.unit, "source": c.source} for c in p.counts],
        "buildings_listed": p.buildings_listed,
        "buildings_listed_is_lower_bound": (p.buildings_listed or 0) >= MAX_BUILDINGS,   # the graph read stopped at its row limit
        "buildings": [],
        "totals_across_all_listed_buildings": {},
        "caveats": [c.as_dict() for c in p.caveats],
        "sources": [GEOSUPPORT, *([PLUTO, HPD] if p.lot is not None else [])],   # the snapshots this answer was read from
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
        out["caveats"].append(CAVEAT_BUILDINGS_CAPPED.format(shown=len(shown), total=len(p.buildings)).as_dict())
    return out


def registrations_to_dict(x: Registrations, max_buildings: int = MAX_BUILDINGS_OUT) -> dict[str, Any]:
    """JSON-safe view of Registrations. Every registration and owner contact is listed as recorded; none is chosen or merged.

    The per-building list is `registration_buildings`, so an answer can point at it apart from the profile's `buildings`.
    """
    r = x.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "buildings_listed": len(x.buildings) if x.lot is not None else None,
        "registration_buildings": [],
        "caveats": [c.as_dict() for c in x.caveats],
        "sources": [GEOSUPPORT, *([HPD] if x.lot is not None else [])],
    }
    shown = sorted(x.buildings, key=lambda b: not b.addressed)[:max_buildings]   # the addressed building always shows
    out["registration_buildings"] = [{
        "bin": b.bin, "address": b.address, "addressed": b.addressed,
        "registrations": [{
            "registrationId": g.registrationId, "lastRegistered": g.lastRegistered, "registrationEnd": g.registrationEnd,
            "owners": [{"contactType": o.contactType, "name": o.name} for o in g.owners],
        } for g in b.registrations],
    } for b in shown]
    if len(x.buildings) > len(shown):
        out["caveats"].append(CAVEAT_REGISTRATION_BUILDINGS_CAPPED.format(shown=len(shown), total=len(x.buildings)).as_dict())
    return out


def deeds_to_dict(x: DeedComparison, max_deeds: int = MAX_DEEDS_OUT, max_pairs: int = MAX_PAIRS_OUT) -> dict[str, Any]:
    """JSON-safe view of a DeedComparison. Every tied deed, grantee and owner is listed as recorded; agreement is per pair, none chosen."""
    r = x.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "deeds": [{
            "documentId": d.documentId, "docType": d.docType, "docDate": d.docDate, "recordedDate": d.recordedDate,
            "amount": d.amount, "otherLots": d.otherLots,
            "grantees": [{"name": g.name, "mailingAddress": g.mailingAddress, "addressLine2": g.addressLine2, "zip": g.zip}
                         for g in d.grantees],
        } for d in x.deeds[:max_deeds]],
        "owners": [{"contactType": o.contactType, "name": o.name, "mailingAddress": o.mailingAddress,
                    "addressLine2": o.addressLine2, "zip": o.zip} for o in x.owners[:MAX_BUILDINGS_OUT]],
        "comparison": [{
            "documentId": p.documentId, "grantee": p.grantee, "owner": p.owner, "ownerType": p.ownerType,
            "nameAgreement": {"outcome": p.nameOutcome, "rule": p.nameRule},
            "addressAgreement": {"outcome": p.addressOutcome, "rule": "A1",
                                 "grantee": dict(zip(ADDRESS_KEYS, p.granteeAddress)), "owner": dict(zip(ADDRESS_KEYS, p.ownerAddress))},
        } for p in x.pairs[:max_pairs]],
        "caveats": [c.as_dict() for c in x.caveats],
        "sources": [GEOSUPPORT, *x.sources],
    }
    if len(x.deeds) > max_deeds:
        out["caveats"].append(CAVEAT_DEEDS_CAPPED.format(shown=max_deeds, total=len(x.deeds)).as_dict())
    if len(x.pairs) > max_pairs:
        out["caveats"].append(CAVEAT_COMPARISON_CAPPED.format(shown=max_pairs, total=len(x.pairs)).as_dict())
    return out


def make_building_profile_tool(client, graph: Graph, pg: ProfileGraph):
    """Bind the profile lookup to its clients. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def building_profile_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """Look up a New York City street address: its tax lot (BBL), the buildings (BIN) HPD lists for it, lot
        characteristics, and counts of violations, complaint problems and litigation per building, with caveats.

        Call this first for any question that starts from a street address. The result is source-reported data:
        violations, problems and litigation are what was cited, reported or brought, not findings of fault. The
        returned caveats are attached to your answer for you; do not restate them. Check status first: ok means a lookup was made (read
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
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    building_profile_tool.name = "building_profile"
    return building_profile_tool


def make_registered_owner_tool(client, graph: Graph, rg: RegistrationGraph):
    """Bind the registered-owner lookup to its clients. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def registered_owner_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """Look up the HPD registrations of the buildings on a New York City street address's tax lot: each registration id,
        its last-registered and end dates, and the owner contacts as recorded (corporate, individual or joint owners only).

        Call this for questions about the registered owner, who registered a building with HPD, or when a registration
        was last filed or ends. A registration records who registered, not who holds title: never call a registrant "the
        owner of the building". Every registration is listed and none is chosen; an empty list means none is recorded,
        not that there is no owner. The data gives an end date but no start, so compare dates yourself against the
        snapshot date in the caveats. Managing agents, officers and site managers are not shown. The returned caveats are
        attached to your answer for you; do not restate them. Check status first: ok means a lookup was made (read
        resolution.outcome for exact, variant, ambiguous or not_found); needs_borough means ask the user for the borough
        or ZIP; invalid_input means the text was not an address; error means an outage or fault, not an answer about
        the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = registered_owners(client, graph, rg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return registrations_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the profile tool: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    registered_owner_tool.name = "registered_owner"
    return registered_owner_tool


def make_deed_vs_owner_tool(client, graph: Graph, rg):
    """Bind the deed-against-registered-owner lookup to its clients. `rg` serves both reads (Neo4jDeedGraph). Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def deed_vs_owner_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """Look up the most recent ACRIS deed(s) on a New York City street address's tax lot, every grantee on them, the HPD
        registered owners, and whether each grantee's name and address agree with each registered owner's.

        Call this for questions about the deed, the grantee, the most recent transfer of title, or whether the deed and the HPD
        registration name the same party. Most recent means the latest recorded date; if several deeds share it, all are listed
        and none is chosen. A deed shows a transfer of title, not a sale (an amount of 0 is common). Name and address agreement are
        two separate fields, each a comparison of recorded strings: exact_normalized or normalization_match is a lead that the
        names are written alike, never proof of the same party, and different is not proof of different parties. Never call a
        grantee or a registrant "the owner". The returned caveats are attached to your answer for you; do not restate them.
        Check status first: ok means a lookup was made (read resolution.outcome for exact, variant, ambiguous or not_found);
        needs_borough means ask the user for the borough or ZIP; invalid_input means the text was not an address; error means an
        outage or fault, not an answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = deed_vs_owner(client, graph, rg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return deeds_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the other tools: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    deed_vs_owner_tool.name = "deed_vs_owner"
    return deed_vs_owner_tool
