"""Agent tools. The model sees only what these return, so every failure is an answer, never an exception
(a catch-all returns status "error" and names only the exception type).

`building_profile` wraps watchline.profile: read-only (Neo4jProfileGraph), row-limited and timed out at the graph,
and capped again here so a lot with hundreds of buildings cannot flood the model's context.
`registered_owner` wraps watchline.registration the same way (Q2: HPD registrations and their owner contacts).
`deed_vs_owner` wraps watchline.deeds (Q3: the most recent deed(s), their grantees, and name and address agreement with the HPD owners).
"""
from typing import Any

from langchain.tools import tool

from watchline.conditions.conditions import Litigation, Violations, litigation_cases, open_violations
from watchline.contacts.contacts import Contacts, building_contacts
from watchline.deeds.deeds import DeedComparison, deed_vs_owner
from watchline.deeds.timeline import DeedTimeline, deed_timeline
from watchline.geosupport.resolution import BoroughRequired, Graph, Match
from watchline.profile.profile import (
    GEOSUPPORT,
    HPD,
    MAX_BUILDINGS,
    PLUTO,
    Caveat,
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
MAX_CONTACTS_OUT = 200
MAX_CASES_OUT = 30
MAX_OWNERS_OUT = 25
MAX_PAIRS_OUT = 100
CAVEAT_DEEDS_CAPPED = CaveatTemplate("deeds_capped", "Showing {shown} of {total} deeds recorded on the latest date; the rest are omitted from this output.")
CAVEAT_OWNERS_CAPPED = CaveatTemplate("owners_capped", "Showing {shown} of {total} registered owner contacts; the rest are omitted from this output.")
CAVEAT_COMPARISON_CAPPED = CaveatTemplate("comparison_capped",
                                          "Showing {shown} of {total} grantee and owner comparisons; the rest are omitted from this output.")
CAVEAT_CONTACTS_CAPPED = CaveatTemplate("contacts_capped", "Showing the first {shown} contacts; the rest are omitted from this output.")
CAVEAT_CASES_CAPPED = CaveatTemplate("cases_capped", "Showing the {shown} most recently opened of {total} cases; the rest are omitted from this output. case_counts covers all {total}.")
CAVEAT_NAMES_CAPPED = Caveat("party_names_capped",
                             ("For at least one deed, only the first distinct party names are listed. The row totals (grantorRows, "
                              "granteeRows) count every party row recorded, including repeats and spelling variants."))
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
                    "addressLine2": o.addressLine2, "zip": o.zip} for o in x.owners[:MAX_OWNERS_OUT]],
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
    if len(x.owners) > MAX_OWNERS_OUT:
        out["caveats"].append(CAVEAT_OWNERS_CAPPED.format(shown=MAX_OWNERS_OUT, total=len(x.owners)).as_dict())
    if len(x.pairs) > max_pairs:
        out["caveats"].append(CAVEAT_COMPARISON_CAPPED.format(shown=max_pairs, total=len(x.pairs)).as_dict())
    return out


def contacts_to_dict(x: Contacts, max_buildings: int = MAX_BUILDINGS_OUT, max_contacts: int = MAX_CONTACTS_OUT) -> dict[str, Any]:
    """JSON-safe view of Contacts. Every contact is listed with the role it was recorded in; none is chosen, merged or matched to another record.

    The per-building list is `contact_buildings`, so an answer can point at it apart from `registration_buildings`.
    """
    r = x.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "buildings_listed": len(x.buildings) if x.lot is not None else None,
        "contact_buildings": [],
        "caveats": [c.as_dict() for c in x.caveats],
        "sources": [GEOSUPPORT, *([HPD] if x.lot is not None else [])],
    }
    shown = sorted(x.buildings, key=lambda b: not b.addressed)[:max_buildings]   # the addressed building always shows
    left, cut = max_contacts, False
    for b in shown:
        regs = []
        for g in b.registrations:
            keep = g.contacts[:max(left, 0)]
            cut = cut or len(keep) < len(g.contacts)
            left -= len(keep)
            regs.append({"registrationId": g.registrationId, "lastRegistered": g.lastRegistered, "registrationEnd": g.registrationEnd,
                         "contacts": [{"role": c.role, "name": c.name, "title": c.title, "mailingAddress": c.mailingAddress,
                                       "addressLine2": c.addressLine2, "zip": c.zip} for c in keep]})
        out["contact_buildings"].append({"bin": b.bin, "address": b.address, "addressed": b.addressed, "registrations": regs})
    if len(x.buildings) > len(shown):
        out["caveats"].append(CAVEAT_REGISTRATION_BUILDINGS_CAPPED.format(shown=len(shown), total=len(x.buildings)).as_dict())
    if cut:
        out["caveats"].append(CAVEAT_CONTACTS_CAPPED.format(shown=max_contacts).as_dict())
    return out


def violations_to_dict(x: Violations, max_buildings: int = MAX_BUILDINGS_OUT) -> dict[str, Any]:
    """JSON-safe view of Violations. Counts stay by building, class and status; `violations_rate` is open violations over the lot's units."""
    r = x.resolution
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "violations": [],
        "violations_rate": None if x.rate is None else {"open": x.rate.open, "units": x.rate.units, "perUnit": x.rate.perUnit,
                                                         "unitsSource": x.rate.unitsSource},
        "caveats": [c.as_dict() for c in x.caveats],
        "sources": [GEOSUPPORT, *x.sources],
    }
    shown = sorted(x.buildings, key=lambda b: not b.addressed)[:max_buildings]
    out["violations"] = [{"bin": b.bin, "address": b.address, "addressed": b.addressed, "oldestOpen": b.oldestOpen,
                          "groups": [{"violationClass": g.violationClass, "status": g.status, "n": g.n, "oldest": g.oldest} for g in b.groups]}
                         for b in shown]
    if len(x.buildings) > len(shown):
        out["caveats"].append(CAVEAT_REGISTRATION_BUILDINGS_CAPPED.format(shown=len(shown), total=len(x.buildings)).as_dict())
    return out


def litigation_to_dict(x: Litigation, max_cases: int = MAX_CASES_OUT) -> dict[str, Any]:
    """JSON-safe view of Litigation. Cases are as recorded; `case_counts` covers every case and is by type, status and finding, never combined."""
    r = x.resolution
    c = x.counts
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "cases": [{
            "bin": k.bin, "litigationId": k.litigationId, "caseType": k.caseType, "caseOpenDate": k.caseOpenDate, "caseStatus": k.caseStatus,
            "openJudgement": k.openJudgement, "harassmentFinding": k.harassmentFinding, "findingDate": k.findingDate, "penalty": k.penalty,
            "isHarassmentFinding": k.isHarassmentFinding, "respondent": k.respondent, "respondentMatch": k.match,
            "matches": [{"part": m.part, "owner": m.owner, "outcome": m.outcome, "rule": m.rule} for m in k.matches],
        } for k in x.cases[:max_cases]],
        "case_counts": None if c is None else {"cases": c.cases, "byType": dict(c.byType), "byStatus": dict(c.byStatus), "byFinding": dict(c.byFinding)},
        "registered_owners": list(x.owners),
        "caveats": [cv.as_dict() for cv in x.caveats],
        "sources": [GEOSUPPORT, *x.sources],
    }
    if len(x.cases) > max_cases:
        out["caveats"].append(CAVEAT_CASES_CAPPED.format(shown=max_cases, total=c.cases if c else len(x.cases)).as_dict())
    return out


def timeline_to_dict(x: DeedTimeline) -> dict[str, Any]:
    """JSON-safe view of a DeedTimeline. Deeds are newest first as recorded; counts are of deeds and cover the whole period, not just the list."""
    r = x.resolution
    c = x.counts
    out: dict[str, Any] = {
        "status": "error" if r.outcome is Match.UNAVAILABLE else "ok",
        "resolution": _resolution_dict(r),
        "lot": x.lot,
        "timeline": [{
            "documentId": d.documentId, "docType": d.docType, "docDate": d.docDate, "recordedDate": d.recordedDate,
            "amount": d.amount, "notSale": d.notSale, "otherLots": d.otherLots,
            "grantors": list(d.grantors), "grantorRows": d.grantorRows, "grantees": list(d.grantees), "granteeRows": d.granteeRows,
        } for d in x.deeds],
        "timeline_counts": None if c is None else {
            "deeds": c.deeds, "notSale": c.notSale, "amountZero": c.amountZero, "byType": dict(c.byType),
            "since": x.since, "until": x.until},
        "caveats": [cv.as_dict() for cv in x.caveats],
        "sources": [GEOSUPPORT, *x.sources],
    }
    if any(d.grantorRows > len(d.grantors) or d.granteeRows > len(d.grantees) for d in x.deeds):
        out["caveats"].append(CAVEAT_NAMES_CAPPED.as_dict())
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


def make_deed_timeline_tool(client, graph: Graph, tg):
    """Bind the deed-timeline lookup to its clients. `tg` is a Neo4jTimelineGraph. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def deed_timeline_tool(address: str, borough: str | None = None, zip_code: str | int | None = None,
                           since: str | None = None, until: str | None = None) -> dict:
        """List every ACRIS deed recorded on a New York City street address's tax lot, newest first: document id, recorded and
        document dates, amount, grantors and grantees as recorded, and counts of deeds.

        Call this for questions about the deed history of a lot, how often it changed hands, whether it was held or transferred, or
        deeds in a period. A deed records a transfer of title, not a sale: an amount of 0, and correction or confirmatory deeds, are
        counted as not a sale, and no deed is called a sale of the building. Counts are of deeds and cover the whole period even when
        the list is capped. Never add counts into one number. Grantor and grantee names are as recorded; variants are not merged and
        none is called "the owner". For the latest deed compared with the HPD registered owner, use deed_vs_owner. The returned
        caveats are attached to your answer for you; do not restate them. Check status first: ok means a lookup was made (read
        resolution.outcome for exact, variant, ambiguous or not_found); needs_borough means ask the user for the borough or ZIP;
        invalid_input means the text was not an address; error means an outage or fault, not an answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
            since: First recorded date to include, as YYYY-MM-DD, only when the user gave a period.
            until: Last recorded date to include, as YYYY-MM-DD, only when the user gave a period.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = deed_timeline(client, graph, tg, address, since=since, until=until, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return timeline_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the other tools: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    deed_timeline_tool.name = "deed_timeline"
    return deed_timeline_tool


def make_building_contacts_tool(client, graph: Graph, cg):
    """Bind the contact lookup to its clients. `cg` is a Neo4jContactGraph. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def building_contacts_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """List the HPD contacts on the registrations of the buildings on a New York City street address's tax lot: managing agent,
        head officer, officers, shareholders, site manager, lessee and the owner contacts, each with the role it was recorded in, its
        recorded title and its business address.

        Call this for questions about who the managing agent, head officer or site manager is, or who can be reached about a
        building. Show a person only with the role recorded; the same name in two roles is two contacts. A managing agent or officer
        is a management or corporate role, never "the owner". A shared address is not evidence that two contacts are one party. Every
        registration is listed; an empty list means none is recorded. The returned caveats are attached to your answer for you; do not
        restate them. Check status first: ok means a lookup was made (read resolution.outcome for exact, variant, ambiguous or
        not_found); needs_borough means ask the user for the borough or ZIP; invalid_input means the text was not an address; error
        means an outage or fault, not an answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = building_contacts(client, graph, cg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return contacts_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the other tools: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    building_contacts_tool.name = "building_contacts"
    return building_contacts_tool


def make_open_violations_tool(client, graph: Graph, cg):
    """Bind the open-violations lookup to its clients. `cg` is a Neo4jConditionsGraph. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def open_violations_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """List the HPD violations of the buildings on a New York City street address's tax lot, by building, class (A, B, C, I) and status
        (Open or Close), with the oldest inspection date of each group, and the open violations per residential unit of the lot.

        Call this for questions about open violations, how long they have been open, or the rate per unit. A violation is what an inspector
        cited, not a finding of fault or a measure of conditions. Report counts by class and status; never add classes into one severity
        number. Open means open at the snapshot date. Units are lot-wide, so the rate pools every listed building; if perUnit is null, say
        the rate is unavailable. Violations exist only for HPD-registered buildings; none recorded is not a clean record. The returned
        caveats are attached to your answer for you; do not restate them. Check status first: ok means a lookup was made (read resolution.outcome for exact, variant, ambiguous or not_found); needs_borough means ask the user for the borough or ZIP; invalid_input means the text was not an address; error means an outage or fault, not an answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = open_violations(client, graph, cg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return violations_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the other tools: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    open_violations_tool.name = "open_violations"
    return open_violations_tool


def make_litigation_cases_tool(client, graph: Graph, cg):
    """Bind the litigation lookup to its clients. `cg` is a Neo4jConditionsGraph. Returns a LangChain tool."""

    @tool(parse_docstring=True)
    def litigation_cases_tool(address: str, borough: str | None = None, zip_code: str | int | None = None) -> dict:
        """List the Housing Court cases HPD brought against the buildings on a New York City street address's tax lot: type, open date, status,
        open judgement, harassment finding and its date, penalty and the respondent as recorded, with counts by type, status and finding
        for all cases.

        Call this for questions about litigation, Housing Court actions, harassment findings or who was named as respondent. A case is an
        action brought, not a finding of fault. Only a harassment finding of After Inquest or After Trial (isHarassmentFinding true) is a
        harassment finding; No Harassment is a recorded outcome of none, and no finding recorded is neither. A respondent that matches a
        registered owner by name (respondentMatch lead) is a lead, never proof of the same party; none means no part matched; roles are
        not recorded. Never call a respondent "the owner". The returned caveats are attached to your answer for you; do not restate them. Check status first: ok means a lookup was made (read resolution.outcome for exact, variant, ambiguous or not_found); needs_borough means ask the user for the borough or ZIP; invalid_input means the text was not an address; error means an outage or fault, not an answer about the address.

        Args:
            address: House number and street as the user typed it, optionally with a borough, ZIP or neighborhood.
            borough: Manhattan, Brooklyn, Queens, Bronx or Staten Island, when the user gave it separately.
            zip_code: Five-digit ZIP, when the user gave it separately.
        """
        try:
            zip5 = None if zip_code is None else str(zip_code).strip()
            try:
                x = litigation_cases(client, graph, cg, address, borough=borough, zip5=zip5)
            except BoroughRequired as e:
                return {"status": "needs_borough", "message": f"{e}. Ask the user for the borough or ZIP; do not guess."}
            except ValueError as e:
                return {"status": "invalid_input", "message": str(e)}
            return litigation_to_dict(x)
        except Exception as e:  # noqa: BLE001  same rule as the other tools: the model gets an answer, never a stack trace
            caveat = ERROR_CAVEAT.format(kind=type(e).__name__)
            return {"status": "error", "message": caveat.text, "caveats": [caveat.as_dict()], "sources": []}

    litigation_cases_tool.name = "litigation_cases"
    return litigation_cases_tool
