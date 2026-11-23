"""Address to HPD registered owner and registration dates (Q2).

Resolution is Q1.3 (watchline.geosupport.resolution). When it lands on a lot we hold, this lists every HPD registration of
every building on the lot: registration id, last-registered and end dates, and the owner contacts as recorded.

A registration records who registered, not who holds title. Nothing is chosen, merged or inferred: all registrations and all
owner contacts are listed, names exactly as recorded, and an empty list means "none recorded".
"""
from dataclasses import dataclass, field
from typing import Protocol

from neo4j import Driver, Query, RoutingControl

from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import (
    CAVEAT_NO_ADDRESSED,
    CAVEAT_NO_ADDRESSED_BIN,
    CAVEAT_NO_BUILDING,
    CAVEAT_NOT_IN_GRAPH,
    CAVEAT_REGISTERED_NO_BUILDING,
    CAVEAT_TRUNCATED,
    MAX_GROUPS,
    TIMEOUT_S,
    Caveat,
    _match_caveats,
    _unresolved_caveat,
)

MAX_ROWS = MAX_GROUPS
OWNER_TYPES = ("CorporateOwner", "IndividualOwner", "JointOwner")   # decision 2026-11-12: the only contact types that are "the owner"
SNAPSHOT_DATE = "2026-05-29"                                         # HPD data through; the source gives an end date, never a start

CAVEAT_NOT_TITLE = Caveat("registrant_not_title",
                          "An HPD registration records who registered the building, not proof of who holds title.")
CAVEAT_PERIOD = Caveat("registration_period",
                       (f"The source gives a registration end date but no period start. Whether a registration is current is read "
                        f"against the data's snapshot date, {SNAPSHOT_DATE}; a registration that ended before it is not current then."))
CAVEAT_OTHER_ROLES = Caveat("owner_not_other_roles",
                            ("The registered owner is not interchangeable with the deed grantee, a process contact or the "
                             "managing agent. Those are separate records and are not shown here."))
CAVEAT_NO_REGISTRATION = Caveat("no_registration_found",
                                ("At least one building listed for the lot has no HPD registration in the data. That says nothing "
                                 "about who owns it, and no owner is inferred."))
CAVEAT_NO_OWNER = Caveat("no_owner_contact",
                         ("At least one registration has no owner contact recorded (an owner type of corporate, individual or "
                          "joint). No owner is inferred; agents, officers and site managers are not owners."))
CAVEAT_BLANK_NAME = Caveat("owner_name_blank",
                           "At least one owner contact is recorded with no name.")


@dataclass(frozen=True)
class RegisteredOwner:
    contactType: str
    name: str | None            # exactly as recorded; None when the record has no name


@dataclass(frozen=True)
class Registration:
    registrationId: int
    lastRegistered: str | None  # ISO date; None when the source has none
    registrationEnd: str | None
    owners: tuple[RegisteredOwner, ...]


@dataclass(frozen=True)
class BuildingRegistrations:
    bin: str
    address: str
    addressed: bool             # the building the typed address resolved to
    registrations: tuple[Registration, ...]


@dataclass(frozen=True)
class Registrations:
    resolution: Answer
    lot: dict | None = None
    buildings: tuple[BuildingRegistrations, ...] = ()
    caveats: tuple[Caveat, ...] = field(default=())


class RegistrationGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def registrations(self, bbl: str) -> list[dict]: ...
    def owners(self, bbl: str) -> list[dict]: ...


def _iso(d) -> str | None:
    return None if d is None else d.iso_format() if hasattr(d, "iso_format") else str(d)


class Neo4jRegistrationGraph:
    """Read-only, parameterized, row-limited, with a server-side timeout. No free-form Cypher from callers."""

    def __init__(self, driver: Driver, database: str):
        self._driver, self._db = driver, database

    def _read(self, text: str, **params) -> list[dict]:
        records = self._driver.execute_query(Query(text, timeout=TIMEOUT_S), params, database_=self._db,
                                             routing_=RoutingControl.READ).records
        return [r.data() for r in records]

    def lot(self, bbl: str) -> dict | None:
        rows = self._read("CYPHER 25 MATCH (l:Lot {bbl: $bbl}) RETURN l.bbl AS bbl, l.hpdRegistered AS hpdRegistered", bbl=bbl)
        return rows[0] if rows else None

    def registrations(self, bbl: str) -> list[dict]:
        """One row per building and registration pair; a building with none gets one row with a null id. Dates are the pair's."""
        rows = self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(b:Building) "
                          "OPTIONAL MATCH (b)-[hr:HAS_REGISTRATION]->(r:Registration) "
                          "RETURN b.bin AS bin, b.address AS address, r.registrationId AS registrationId, "
                          "hr.lastRegistered AS lastRegistered, hr.registrationEnd AS registrationEnd "
                          "ORDER BY bin, registrationId LIMIT $limit", bbl=bbl, limit=MAX_ROWS)
        return [{**r, "lastRegistered": _iso(r["lastRegistered"]), "registrationEnd": _iso(r["registrationEnd"])} for r in rows]

    def owners(self, bbl: str) -> list[dict]:
        """Owner contacts by registration. DISTINCT collapses exact duplicates (same registration, type and name)."""
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(:Building)-[:HAS_REGISTRATION]->"
                          "(r:Registration)-[:HAS_CONTACT]->(c:Contact WHERE c.contactType IN $types) "
                          "RETURN DISTINCT r.registrationId AS registrationId, c.contactType AS contactType, "
                          "coalesce(c.corporationName, c.personName) AS name "
                          "ORDER BY registrationId, contactType, name LIMIT $limit", bbl=bbl, types=list(OWNER_TYPES), limit=MAX_ROWS)


def build_registrations(resolution: Answer, rg: RegistrationGraph) -> Registrations:
    """Pure given the graph rows. The resolution decides whether there is anything to read."""
    caveats = _match_caveats(resolution)
    unresolved = _unresolved_caveat(resolution)
    lot = rg.lot(resolution.bbl) if unresolved is None and resolution.bbl else None
    if unresolved is None and lot is None:
        unresolved = CAVEAT_NOT_IN_GRAPH.format(bbl=resolution.bbl)
    if unresolved:
        return Registrations(resolution, caveats=(*caveats, unresolved))

    rows, owner_rows = rg.registrations(resolution.bbl), rg.owners(resolution.bbl)
    owners_by_reg: dict[int, list[RegisteredOwner]] = {}
    for o in owner_rows:
        item = RegisteredOwner(o["contactType"], o["name"] or None)
        bucket = owners_by_reg.setdefault(o["registrationId"], [])
        if item not in bucket:                      # exact duplicates are one contact
            bucket.append(item)

    by_bin: dict[str, dict] = {}
    for r in rows:
        b = by_bin.setdefault(r["bin"], dict(address=r["address"], registrations=[]))
        if r["registrationId"] is not None:
            b["registrations"].append(Registration(
                r["registrationId"], r["lastRegistered"], r["registrationEnd"], tuple(owners_by_reg.get(r["registrationId"], ()))))
    buildings = tuple(BuildingRegistrations(bin=k, address=v["address"], addressed=k == resolution.bin,
                                            registrations=tuple(v["registrations"])) for k, v in by_bin.items())

    if not buildings:
        caveats.append(CAVEAT_REGISTERED_NO_BUILDING if lot.get("hpdRegistered") else CAVEAT_NO_BUILDING)
        return Registrations(resolution, lot=lot, caveats=tuple(caveats))

    regs = [g for b in buildings for g in b.registrations]
    caveats += [CAVEAT_NOT_TITLE, CAVEAT_PERIOD, CAVEAT_OTHER_ROLES]
    if any(not b.registrations for b in buildings):
        caveats.append(CAVEAT_NO_REGISTRATION)
    if any(not g.owners for g in regs):
        caveats.append(CAVEAT_NO_OWNER)
    if any(o.name is None for g in regs for o in g.owners):
        caveats.append(CAVEAT_BLANK_NAME)
    if not any(b.addressed for b in buildings):
        caveats.append(CAVEAT_NO_ADDRESSED.format(bin=resolution.bin) if resolution.bin else CAVEAT_NO_ADDRESSED_BIN)
    if max(len(rows), len(owner_rows)) >= MAX_ROWS:
        caveats.append(CAVEAT_TRUNCATED)
    return Registrations(resolution, lot=lot, buildings=buildings, caveats=tuple(caveats))


def registered_owners(client, graph: Graph, rg: RegistrationGraph, text: str, **kw) -> Registrations:
    """Typed address to registrations. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_registrations(resolve_text(client, graph, text, **kw), rg)
