"""Entity research (Q5, PESP step 5): what the New York DOS active-entity snapshot says about the owner entities of a lot.

Resolution is Q1.3. The names looked up are the corporate registered owners on the lot's HPD registrations and the entity-like grantees of the latest deed, each as recorded. A name
is matched to DOS records by its name key (the graph's normalization, rule N3): every record that shares the key is returned and none is chosen. A match by name is a lead, never proof
that the DOS entity is the owner. No record in the snapshot is not "does not exist": dissolved entities are absent. Individuals are not looked up. The DOS process name and address are
where the state forwards legal papers, not who runs the entity; no officers, managers or members are carried.
"""
import re
from dataclasses import dataclass, field
from typing import Protocol

from watchline.deeds.deeds import CAVEAT_NAME_NOT_IDENTITY, CAVEAT_SHARED_ADDRESS, DEED_TYPES
from watchline.geosupport.resolution import Answer, Graph, resolve_text
from watchline.profile.profile import CAVEAT_NOT_IN_GRAPH, Caveat, _match_caveats, _unresolved_caveat
from watchline.registration.registration import MAX_ROWS, Neo4jRegistrationGraph

DOS = "New York State DOS active entities (data through 2026-07-06)"        # the snapshot date is from specs/questions/q05.md; the graph does not carry it
MAX_NAMES = 25
DEFAULT_PROCESS_NAMES = ("THE COMPANY", "THE LIMITED LIABILITY COMPANY")      # the statutory default: not a person, not a lead
ENTITY_WORDS = re.compile(r"\b(LLC|L\.?L\.?C\.?|INC\.?|INCORPORATED|CORP\.?|CORPORATION|CO\.?|COMPANY|LP|L\.?P\.?|LLP|LTD\.?|LIMITED|TRUST|ASSOCIATES|PARTNERS|HDFC|REALTY|HOLDINGS|PROPERTIES|ENTERPRISES|OWNERS)\b", re.I)

CAVEAT_NO_RECORD = Caveat("dos_no_record_not_absence",
                          "No record in the active-entity snapshot is not a statement that the entity does not exist: dissolved entities, and entities under a different spelling, are absent.")
CAVEAT_PROCESS = Caveat("dos_process_not_operator",
                        "The DOS process name and address are where the state forwards legal papers. They do not say who runs the entity, and no officers, managers or members are carried.")
CAVEAT_DEFAULT = Caveat("dos_default_process_name", "The statutory default process name (THE COMPANY, THE LIMITED LIABILITY COMPANY) is not a person and not a lead.")
CAVEAT_SEVERAL = Caveat("dos_several_records", "More than one record shares this name. All are shown and none is chosen.")
CAVEAT_INDIVIDUALS = Caveat("individuals_not_looked_up", "Individuals are not looked up: the snapshot holds corporations and similar entities only.")
CAVEAT_NOTHING = Caveat("no_entity_names", "The lot has no corporate registered owner and the latest deed names no entity, so there was nothing to look up.")


@dataclass(frozen=True)
class DosRecord:
    dosId: int
    name: str
    entityType: str | None
    jurisdiction: str | None
    filingDate: str | None
    processName: str | None
    processAddress: str | None          # street, second line, city, state and ZIP joined
    agentName: str | None
    agentAddress: str | None
    processAddressEntities: int | None  # entities in the snapshot that use the same process address (this one included)


@dataclass(frozen=True)
class Subject:
    name: str                           # as recorded
    key: str                            # the name key the DOS records were matched on
    roles: tuple[str, ...]              # registered owner, latest deed grantee
    records: tuple[DosRecord, ...]


@dataclass(frozen=True)
class EntityResearch:
    resolution: Answer
    lot: dict | None = None
    subjects: tuple[Subject, ...] = ()
    skipped: int = 0                    # grantees that are individuals or not entity-like, not looked up
    caveats: tuple[Caveat, ...] = field(default=())
    sources: tuple[str, ...] = ()


class EntityGraph(Protocol):
    def lot(self, bbl: str) -> dict | None: ...
    def owner_entities(self, bbl: str) -> list[dict]: ...
    def latest_grantees(self, bbl: str) -> list[dict]: ...
    def dos_records(self, keys: list[str]) -> list[dict]: ...


class Neo4jEntityGraph(Neo4jRegistrationGraph):
    """Read-only, parameterized, row-limited, with a server-side timeout. No free-form Cypher from callers."""

    def owner_entities(self, bbl: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_BUILDING]->(:Building)-[:HAS_REGISTRATION]->(:Registration)-[:HAS_CONTACT]->"
                          "(c:Contact {contactType: 'CorporateOwner'}) WHERE c.corporationName IS NOT NULL AND c.nameKey IS NOT NULL "
                          "RETURN DISTINCT c.corporationName AS name, c.nameKey AS key ORDER BY name LIMIT $limit", bbl=bbl, limit=MAX_NAMES)

    def latest_grantees(self, bbl: str) -> list[dict]:
        """The distinct grantee names of the deed(s) with the latest recorded date."""
        return self._read("CYPHER 25 MATCH (:Lot {bbl: $bbl})-[:HAS_DEED]->(d:Deed WHERE d.docType IN $types) WITH max(d.recordedDate) AS latest "
                          "MATCH (:Lot {bbl: $bbl})-[:HAS_DEED]->(d:Deed WHERE d.docType IN $types AND d.recordedDate = latest)-[:HAS_GRANTEE]->(g:Grantee) "
                          "WHERE g.name IS NOT NULL AND g.nameKey IS NOT NULL RETURN DISTINCT g.name AS name, g.nameKey AS key ORDER BY name LIMIT $limit",
                          bbl=bbl, types=list(DEED_TYPES), limit=MAX_NAMES)

    def dos_records(self, keys: list[str]) -> list[dict]:
        return self._read("CYPHER 25 MATCH (e:DosEntity WHERE e.nameKey IN $keys) "
                          "RETURN e.nameKey AS key, e.dosId AS dosId, e.name AS name, e.entityType AS entityType, e.jurisdiction AS jurisdiction, "
                          "e.filingDate AS filingDate, e.processName AS processName, e.processAddress AS processAddress, e.processAddressLine2 AS processAddressLine2, "
                          "e.processCity AS processCity, e.processState AS processState, e.processZip AS processZip, e.agentName AS agentName, "
                          "e.agentAddress AS agentAddress, e.agentAddressLine2 AS agentAddressLine2, e.agentCity AS agentCity, e.agentState AS agentState, "
                          "e.agentZip AS agentZip, e.processAddressEntities AS processAddressEntities ORDER BY key, dosId LIMIT $limit", keys=keys, limit=MAX_ROWS)


def _where(*parts) -> str | None:
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


def _iso(d) -> str | None:
    return None if d is None else d.iso_format() if hasattr(d, "iso_format") else str(d)


def _record(r: dict) -> DosRecord:
    return DosRecord(r["dosId"], r["name"], r.get("entityType"), r.get("jurisdiction"), _iso(r.get("filingDate")), r.get("processName"),
                     _where(r.get("processAddress"), r.get("processAddressLine2"), r.get("processCity"), r.get("processState"), r.get("processZip")),
                     r.get("agentName"), _where(r.get("agentAddress"), r.get("agentAddressLine2"), r.get("agentCity"), r.get("agentState"), r.get("agentZip")),
                     r.get("processAddressEntities"))


def build_entities(resolution: Answer, eg: EntityGraph) -> EntityResearch:
    """Pure given the graph rows. The resolution decides whether there is anything to read."""
    caveats = _match_caveats(resolution)
    unresolved = _unresolved_caveat(resolution)
    lot = eg.lot(resolution.bbl) if unresolved is None and resolution.bbl else None
    if unresolved is None and lot is None:
        unresolved = CAVEAT_NOT_IN_GRAPH.format(bbl=resolution.bbl)
    if unresolved:
        return EntityResearch(resolution, caveats=(*caveats, unresolved))

    named: dict[str, dict] = {}                                  # key -> {"name", "roles"}
    for r in eg.owner_entities(resolution.bbl):
        named.setdefault(r["key"], dict(name=r["name"], roles=[]))["roles"].append("registered owner")
    skipped = 0
    for r in eg.latest_grantees(resolution.bbl):
        slot = named.get(r["key"])
        if slot is not None:
            slot["roles"].append("latest deed grantee")
            continue
        named[r["key"]] = dict(name=r["name"], roles=["latest deed grantee"], entityLike=bool(ENTITY_WORDS.search(r["name"])))
    records: dict[str, list[DosRecord]] = {}
    for r in eg.dos_records(sorted(named)) if named else []:
        records.setdefault(r["key"], []).append(_record(r))
    subjects = []
    for key, v in sorted(named.items(), key=lambda kv: kv[1]["name"]):
        found = tuple(records.get(key, ()))
        if not found and not v.get("entityLike", True):
            skipped += 1                                         # a grantee that is a person: no DOS record is expected, and saying "none" would imply one was
            continue
        subjects.append(Subject(v["name"], key, tuple(v["roles"]), found))

    if not subjects:
        return EntityResearch(resolution, lot=lot, skipped=skipped, caveats=(*caveats, CAVEAT_NOTHING, *([CAVEAT_INDIVIDUALS] if skipped else [])), sources=(DOS,))
    caveats += [CAVEAT_PROCESS, CAVEAT_NAME_NOT_IDENTITY]
    if any(not s.records for s in subjects):
        caveats.append(CAVEAT_NO_RECORD)
    if any(len(s.records) > 1 for s in subjects):
        caveats.append(CAVEAT_SEVERAL)
    if any(x.processName in DEFAULT_PROCESS_NAMES for s in subjects for x in s.records):
        caveats.append(CAVEAT_DEFAULT)
    if any((x.processAddressEntities or 0) > 1 for s in subjects for x in s.records):
        caveats.append(CAVEAT_SHARED_ADDRESS)
    if skipped:
        caveats.append(CAVEAT_INDIVIDUALS)
    return EntityResearch(resolution, lot=lot, subjects=tuple(subjects), skipped=skipped, caveats=tuple(dict.fromkeys(caveats)), sources=(DOS,))


def entity_research(client, graph: Graph, eg: EntityGraph, text: str, **kw) -> EntityResearch:
    """Typed address to the DOS records of its owner entities. Raises BoroughRequired or ValueError from resolve_text: ask, never guess."""
    return build_entities(resolve_text(client, graph, text, **kw), eg)


def entities_view(x: EntityResearch) -> dict:
    """JSON-safe view, the shape the report section reads."""
    r = x.resolution
    return {
        "status": "ok", "resolution": {"input": r.input, "outcome": str(r.outcome), "bbl": r.bbl, "bin": r.bin, "returned": r.returned},
        "lot": x.lot, "skipped": x.skipped,
        "subjects": [{"name": s.name, "key": s.key, "roles": list(s.roles), "records": [{
            "dosId": d.dosId, "name": d.name, "entityType": d.entityType, "jurisdiction": d.jurisdiction, "filingDate": d.filingDate, "processName": d.processName,
            "processAddress": d.processAddress, "agentName": d.agentName, "agentAddress": d.agentAddress, "processAddressEntities": d.processAddressEntities,
            "defaultProcessName": d.processName in DEFAULT_PROCESS_NAMES} for d in s.records]} for s in x.subjects],
        "caveats": [c.as_dict() for c in x.caveats], "sources": list(x.sources),
    }
