"""Address to the HPD contacts of each registration, with the role each was recorded in (Q4).

Resolution is Q1.3 and the registrations are Q2. This adds every contact on every registration of every building on the lot, whatever its
recorded role (agent, head officer, officer, shareholder, site manager, lessee, and the owner types), with the recorded title and the
business address. Nothing is chosen, merged or inferred: a name is shown with the role it was recorded in, the same name in two roles is two
contacts, and an empty list means "none recorded". A managing agent is a management relationship, not ownership.
"""
from dataclasses import dataclass, field
from typing import Protocol

from watchline.deeds.deeds import CAVEAT_SHARED_ADDRESS
from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import CAVEAT_TRUNCATED, Caveat
from watchline.registration import registration as R
from watchline.registration.registration import MAX_ROWS, Neo4jRegistrationGraph, RegistrationGraph

OWNER_ROLES = R.OWNER_TYPES

CAVEAT_ROLE_AS_RECORDED = Caveat("role_as_recorded",
                                 ("A person is shown only in the role HPD recorded. The same name in two roles is two contacts, and a "
                                  "contact's name is not matched to any other record here."))
CAVEAT_AGENT_NOT_OWNER = Caveat("agent_not_owner",
                                "A managing agent, officer or site manager is a management or corporate role, not evidence of ownership.")
CAVEAT_NO_CONTACTS = Caveat("no_contacts_found",
                            "At least one registration has no contact recorded. That says nothing about who manages or owns the building.")


@dataclass(frozen=True)
class Contact:
    role: str                       # contactType as recorded: Agent, HeadOfficer, Officer, Shareholder, SiteManager, Lessee, owner types
    name: str | None                # exactly as recorded; a company name or a person's name
    title: str | None = None        # the recorded title (for example PRESIDENT), when there is one
    mailingAddress: str | None = None
    addressLine2: str | None = None
    zip: str | None = None


@dataclass(frozen=True)
class RegistrationContacts:
    registrationId: int
    lastRegistered: str | None
    registrationEnd: str | None
    contacts: tuple[Contact, ...]


@dataclass(frozen=True)
class BuildingContacts:
    bin: str
    address: str
    addressed: bool
    registrations: tuple[RegistrationContacts, ...]


@dataclass(frozen=True)
class Contacts:
    resolution: Answer
    lot: dict | None = None
    buildings: tuple[BuildingContacts, ...] = ()
    caveats: tuple[Caveat, ...] = field(default=())


class ContactGraph(RegistrationGraph, Protocol):
    def contacts(self, bbl: str) -> list[dict]: ...


class Neo4jContactGraph(Neo4jRegistrationGraph):
    """The registration reads plus the contact read. Read-only, parameterized, row-limited, with a server-side timeout."""

    def contacts(self, bbl: str) -> list[dict]:
        """Every contact by registration, of every recorded type. DISTINCT collapses exact duplicates."""
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(:Building)-[:HAS_REGISTRATION]->"
                          "(r:Registration)-[:HAS_CONTACT]->(c:Contact) "
                          "RETURN DISTINCT r.registrationId AS registrationId, c.contactType AS role, "
                          "coalesce(c.corporationName, c.personName) AS name, c.title AS title, c.mailingAddress AS mailingAddress, "
                          "c.addressLine2 AS addressLine2, c.zip AS zip "
                          "ORDER BY registrationId, role, name, mailingAddress LIMIT $limit", bbl=bbl, limit=MAX_ROWS)


def _shared_address(contacts: tuple[Contact, ...]) -> bool:
    keys = [(c.mailingAddress.upper(), (c.zip or "")[:5]) for c in contacts if c.mailingAddress]
    return len(keys) != len(set(keys))


def build_contacts(resolution: Answer, cg: ContactGraph) -> Contacts:
    """Pure given the graph rows. Registrations give the buildings and dates; the contact read adds who is listed on each."""
    regs = R.build_registrations(resolution, cg)
    # Q2's title, owner-only and other-roles caveats are about the owner view; this answer shows every role.
    caveats = [c for c in regs.caveats if c not in (R.CAVEAT_OTHER_ROLES, R.CAVEAT_NO_OWNER, R.CAVEAT_BLANK_NAME)]
    if regs.lot is None or not regs.buildings:
        return Contacts(resolution, lot=regs.lot, caveats=tuple(caveats))

    rows = cg.contacts(resolution.bbl)
    by_reg: dict[int, list[Contact]] = {}
    for r in rows:
        item = Contact(r["role"], r.get("name") or None, r.get("title") or None, r.get("mailingAddress") or None,
                       r.get("addressLine2") or None, r.get("zip") or None)
        bucket = by_reg.setdefault(r["registrationId"], [])
        if item not in bucket:
            bucket.append(item)

    buildings = tuple(BuildingContacts(
        b.bin, b.address, b.addressed,
        tuple(RegistrationContacts(g.registrationId, g.lastRegistered, g.registrationEnd, tuple(by_reg.get(g.registrationId, ())))
              for g in b.registrations)) for b in regs.buildings)
    every = [g for b in buildings for g in b.registrations]
    caveats += [CAVEAT_ROLE_AS_RECORDED]
    if any(c.role not in OWNER_ROLES for g in every for c in g.contacts):
        caveats.append(CAVEAT_AGENT_NOT_OWNER)
    if any(not g.contacts for g in every):
        caveats.append(CAVEAT_NO_CONTACTS)
    if any(_shared_address(g.contacts) for g in every):
        caveats.append(CAVEAT_SHARED_ADDRESS)
    if len(rows) >= MAX_ROWS:
        caveats.append(CAVEAT_TRUNCATED)
    return Contacts(resolution, lot=regs.lot, buildings=buildings, caveats=tuple(dict.fromkeys(caveats)))


def building_contacts(client, graph: Graph, cg: ContactGraph, text: str, **kw) -> Contacts:
    """Typed address to contacts. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_contacts(resolve_text(client, graph, text, **kw), cg)
