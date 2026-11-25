"""The identity checkpoint, step 2: read landlord parties and candidate links from the graph (design: docs/plans/identity-checkpoint.md).

Everything is looked up by the landlord name as recorded, never by a run-local portfolio, network or node id (node ids are used only
inside one call, to follow edges). Landlord records that the graph joined by identity (`CONNECTED_BY_IDENTITY`) are one party. Name and
address edges (`CONNECTED_BY_NAME`, `CONNECTED_BY_ADDRESS`) that leave the anchor party are candidate links, each a lead for the researcher.
Deed edges are not read here: a deed shows ownership, not shared operation.

Masks are matched on the address as spelled (street line and ZIP), so an address spelled differently from the lists is not flagged. The
presence of an address edge already means the network method did not mask that address.
"""
import re
from dataclasses import dataclass, field
from typing import Protocol

from watchline.deeds.names import name_agreement
from watchline.identity.checkpoint import Evidence, Link, Lot, Party
from watchline.profile.profile import MAX_GROUPS, Caveat
from watchline.registration.registration import Neo4jRegistrationGraph

MAX_RECORDS = 500                 # identity closure size; beyond it the party is cut and flagged
MAX_ROUNDS = 8
MAX_PARTIES = 100                 # candidate parties per anchor; beyond it the rest are omitted and flagged
SOURCE_NETWORK = "BOR operational network (landlord links)"
SOURCE_HPD = "HPD contacts (business addresses on landlord records)"
SOURCE_REGISTRATIONS = "HPD registrations (contacts listed on each registration)"
MAX_REGISTRATION_ROWS = 500
MAX_REGISTRATION_ITEMS = 10      # evidence items kept per link; the text says how many more there are

CAVEAT_CUT = Caveat("identity_party_cut", "A party or the list of candidate parties was cut at a size limit, so the portfolio may be incomplete.")
CAVEAT_REGISTRATION_NAMES = Caveat("registration_names_as_recorded",
                                   ("Names on a registration are matched as spelled (upper-cased). A registration that lists two names shows both were "
                                    "listed there in the roles recorded; it does not show they are one party, and a person is shown only in the role recorded."))
CAVEAT_MASK_AS_SPELLED = Caveat("mask_matched_as_spelled",
                                ("Masked and mail-drop addresses are matched on the address as spelled (street line and ZIP). An address "
                                 "spelled differently is not flagged."))
CAVEAT_NO_DEED_LINKS = Caveat("deed_links_not_read",
                              "Landlord links made only by a shared deed are not shown. A deed shows ownership, not shared operation.")


class IdentityGraph(Protocol):
    def records_named(self, name: str) -> list[dict]: ...
    def records(self, ids: list[int]) -> list[dict]: ...
    def identity_pairs(self, ids: list[int]) -> list[dict]: ...
    def lots(self, ids: list[int]) -> list[dict]: ...
    def lead_edges(self, ids: list[int]) -> list[dict]: ...
    def masks(self, streets: list[str]) -> list[dict]: ...
    def shared_registrations(self, bbls: list[str], names_a: list[str], names_b: list[str]) -> list[dict]: ...


class Neo4jIdentityGraph(Neo4jRegistrationGraph):
    """Read-only, parameterized, row-limited, with a server-side timeout. No free-form Cypher from callers."""

    def records_named(self, name: str) -> list[dict]:
        return self._read("CYPHER 25 MATCH (n:Landlord {name: $name}) RETURN n.nodeId AS nodeId, n.name AS name, "
                          "n.businessAddresses AS businessAddresses ORDER BY nodeId LIMIT $limit", name=name, limit=MAX_RECORDS)

    def records(self, ids: list[int]) -> list[dict]:
        return self._read("CYPHER 25 MATCH (n:Landlord WHERE n.nodeId IN $ids) RETURN n.nodeId AS nodeId, n.name AS name, "
                          "n.businessAddresses AS businessAddresses ORDER BY nodeId LIMIT $limit", ids=ids, limit=MAX_RECORDS)

    def identity_pairs(self, ids: list[int]) -> list[dict]:
        return self._read("CYPHER 25 MATCH (a:Landlord WHERE a.nodeId IN $ids)-[:CONNECTED_BY_IDENTITY]-(b:Landlord) "
                          "RETURN DISTINCT a.nodeId AS nodeId, b.nodeId AS peerId ORDER BY nodeId, peerId LIMIT $limit",
                          ids=ids, limit=MAX_GROUPS)

    def lots(self, ids: list[int]) -> list[dict]:
        """The lots each record covers. Units are the lot's value, never a building's."""
        return self._read("CYPHER 25 MATCH (n:Landlord WHERE n.nodeId IN $ids)-[:COVERS]->(l:Lot) "
                          "RETURN n.nodeId AS nodeId, l.bbl AS bbl, l.unitsRes AS unitsRes ORDER BY bbl, nodeId LIMIT $limit",
                          ids=ids, limit=MAX_GROUPS)

    def lead_edges(self, ids: list[int]) -> list[dict]:
        """Name and address edges that leave the set of records."""
        return self._read("CYPHER 25 MATCH (a:Landlord WHERE a.nodeId IN $ids)-[r:CONNECTED_BY_ADDRESS|CONNECTED_BY_NAME]-"
                          "(b:Landlord WHERE NOT b.nodeId IN $ids) "
                          "RETURN a.nodeId AS fromId, b.nodeId AS toId, type(r) AS type, r.weight AS weight "
                          "ORDER BY toId, type, fromId LIMIT $limit", ids=ids, limit=MAX_GROUPS)

    def shared_registrations(self, bbls: list[str], names_a: list[str], names_b: list[str]) -> list[dict]:
        """Registrations of buildings on these lots that list a contact named in names_a and a contact named in names_b (upper-cased, as recorded)."""
        return self._read("CYPHER 25 MATCH (l:Lot WHERE l.bbl IN $bbls)-[:HAS_BUILDING]->(b:Building)-[:HAS_REGISTRATION]->(r:Registration) "
                          "MATCH (r)-[:HAS_CONTACT]->(ca:Contact WHERE toUpper(coalesce(ca.corporationName, ca.personName)) IN $namesA) "
                          "MATCH (r)-[:HAS_CONTACT]->(cb:Contact WHERE toUpper(coalesce(cb.corporationName, cb.personName)) IN $namesB) "
                          "RETURN DISTINCT r.registrationId AS registrationId, l.bbl AS bbl, b.address AS address, "
                          "toUpper(coalesce(ca.corporationName, ca.personName)) AS nameA, ca.contactType AS roleA, "
                          "toUpper(coalesce(cb.corporationName, cb.personName)) AS nameB, cb.contactType AS roleB "
                          "ORDER BY registrationId, bbl, nameA, roleA, nameB, roleB LIMIT $limit",
                          bbls=bbls, namesA=names_a, namesB=names_b, limit=MAX_REGISTRATION_ROWS)

    def masks(self, streets: list[str]) -> list[dict]:
        """Which of these street lines the masks and the mail-drop list carry (matched as spelled)."""
        return self._read("CYPHER 25 MATCH (m:NetworkMaskedAddress WHERE m.address IN $streets) "
                          "RETURN 'network' AS list, m.address AS address, m.degree AS degree, null AS kind, null AS zip5, null AS status "
                          "UNION ALL MATCH (m:PortfolioMaskedAddress WHERE m.address IN $streets) "
                          "RETURN 'portfolio' AS list, m.address AS address, m.degree AS degree, null AS kind, null AS zip5, null AS status "
                          "UNION ALL MATCH (m:MailDropAddress WHERE m.address IN $streets) "
                          "RETURN 'maildrop' AS list, m.address AS address, null AS degree, m.kind AS kind, m.zip5 AS zip5, "
                          "m.reviewStatus AS status", streets=streets)


# ---- pure part ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Inputs:
    status: str                                   # ok, not_found, ambiguous_name
    name: str
    anchor: Party | None = None
    links: tuple[Link, ...] = ()
    candidates: tuple[tuple[str, int], ...] = ()  # ambiguous_name: each party the name falls into, with its lot count
    caveats: tuple[Caveat, ...] = field(default=())


def _street_zip(addr: str) -> tuple[str, str | None, str | None]:
    """The street line, the ZIP and a unit-joined street, from 'STREET, [unit,] City, ST ZIP'."""
    parts = [p.strip() for p in addr.split(",")]
    street = re.sub(r"\s+", " ", parts[0]).upper()
    m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", addr)
    unit = f"{street} {re.sub(r'\s+', ' ', parts[1]).upper()}" if len(parts) >= 4 else None
    return street, (m.group(1) if m else None), unit


def _mask_reason(addr: str, masks: dict[str, list[dict]]) -> str | None:
    street, zip5, unit = _street_zip(addr)
    for key in filter(None, (street, unit)):
        for m in masks.get(key, ()):
            if m["list"] == "network":
                return f"masked by the network method (degree {m['degree']})"
            if m["list"] == "portfolio":
                return f"masked by the portfolio method (degree {m['degree']})"
            if m["list"] == "maildrop" and m["zip5"] == zip5:
                return f"on the mail-drop list ({m['kind']}, {m['status']})"
    return None


def _full(rows: list) -> bool:
    """True when a read returned as many rows as its limit, so it may have been cut."""
    return len(rows) >= MAX_GROUPS


def _closure(ig: IdentityGraph, seed: set[int]) -> tuple[set[int], bool]:
    """The records joined to the seed by identity edges, and whether the size or round limit cut it."""
    seen, frontier, cut = set(seed), set(seed), False
    for _ in range(MAX_ROUNDS):
        if not frontier:
            return seen, cut
        pairs = ig.identity_pairs(sorted(frontier))
        cut = cut or _full(pairs)
        new = {r["peerId"] for r in pairs} - seen
        seen |= new
        frontier = new
        if len(seen) >= MAX_RECORDS:
            return seen, True
    return seen, cut or bool(frontier)


def _party(key: str, ids: set[int], recs: dict[int, dict], lots: list[dict]) -> Party:
    by_bbl: dict[str, Lot] = {}
    for r in lots:
        if r["nodeId"] in ids:
            by_bbl.setdefault(r["bbl"], Lot(r["bbl"], r.get("unitsRes")))
    return Party(key, tuple(sorted(by_bbl.values(), key=lambda x: x.bbl)), records=len(ids))


def _key(ids: set[int], recs: dict[int, dict]) -> str:
    return " / ".join(sorted({recs[i]["name"] for i in ids if i in recs}))


def _registration_evidence(rows: list[dict]) -> tuple[Evidence, ...]:
    """One evidence item per registration and lot: which names it lists, each with the roles it was recorded in."""
    by_reg: dict[tuple, dict[str, set[str]]] = {}
    for r in rows:
        roles = by_reg.setdefault((r["registrationId"], r["bbl"], r.get("address") or ""), {})
        roles.setdefault(r["nameA"], set()).add(r["roleA"])
        roles.setdefault(r["nameB"], set()).add(r["roleB"])
    items = []
    for (rid, bbl, address), roles in sorted(by_reg.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        listed = "; ".join(f"{n} as {' and '.join(sorted(rs))}" for n, rs in sorted(roles.items()))
        items.append(Evidence("shared_contact", f"HPD registration {rid} of lot {bbl} ({address}) lists {listed}.", SOURCE_REGISTRATIONS))
    if len(items) > MAX_REGISTRATION_ITEMS:
        more = len(items) - MAX_REGISTRATION_ITEMS
        items = [*items[:MAX_REGISTRATION_ITEMS], Evidence("shared_contact", f"{more} more registrations list both names.", SOURCE_REGISTRATIONS)]
    return tuple(items)


def build_inputs(ig: IdentityGraph, name: str) -> Inputs:
    """Pure given the graph rows. The anchor is every landlord record with this exact name, followed through identity edges.

    If those records fall into more than one identity group, nothing is chosen: the groups are listed for the researcher to pick.
    """
    named = ig.records_named(name)
    if not named:
        return Inputs("not_found", name)
    caveats: list[Caveat] = [CAVEAT_NO_DEED_LINKS]
    cut = False

    groups: list[set[int]] = []
    assigned: set[int] = set()
    for r in named:
        if r["nodeId"] in assigned:
            continue
        g, c = _closure(ig, {r["nodeId"]})
        groups.append(g)
        assigned |= g
        cut = cut or c
    if len(groups) > 1:
        ids = sorted(set().union(*groups))
        recs = {r["nodeId"]: r for r in ig.records(ids)}
        lots = ig.lots(ids)
        cut = cut or _full(lots)
        cands = tuple(sorted((_key(g, recs), len(_party("", g, recs, lots).lots)) for g in groups))
        return Inputs("ambiguous_name", name, candidates=cands, caveats=tuple([*caveats, *([CAVEAT_CUT] if cut else [])]))

    anchor_ids = groups[0]
    edges = ig.lead_edges(sorted(anchor_ids))
    cut = cut or _full(edges)
    other_ids = {e["toId"] for e in edges}
    others: list[set[int]] = []
    placed: set[int] = set()
    for i in sorted(other_ids):
        if i in placed:
            continue
        g, c = _closure(ig, {i})
        g -= anchor_ids
        others.append(g)
        placed |= g
        cut = cut or c
    others.sort(key=min)
    if len(others) > MAX_PARTIES:
        others, cut = others[:MAX_PARTIES], True

    every = sorted(anchor_ids | set().union(*others)) if others else sorted(anchor_ids)
    recs = {r["nodeId"]: r for r in ig.records(every)}
    lots = ig.lots(every)
    cut = cut or _full(lots)

    def addresses(ids: set[int]) -> list[str]:
        return sorted({a for i in ids for a in (recs.get(i, {}).get("businessAddresses") or [])})

    streets = sorted({s for g in [anchor_ids, *others] for a in addresses(g) for s in filter(None, (_street_zip(a)[0], _street_zip(a)[2]))})
    masks: dict[str, list[dict]] = {}
    for m in ig.masks(streets) if streets else []:
        masks.setdefault(m["address"], []).append(m)

    anchor = _party(_key(anchor_ids, recs), anchor_ids, recs, lots)
    parties = [(_party(_key(g, recs), g, recs, lots), g) for g in others]
    seen_keys = {anchor.key}
    fixed = []
    for p, g in sorted(parties, key=lambda t: (t[0].key, t[0].lots[0].bbl if t[0].lots else "", len(t[0].lots), t[0].records)):
        base = p.key
        if base in seen_keys:                                    # same name on a different group: tell them apart by a lot, not an id
            base = f"{p.key} [lot {p.lots[0].bbl if p.lots else 'none'}]"
        key, n = base, 1
        while key in seen_keys:                                  # still the same (same first lot, or no lot): number them in the fixed order
            n += 1
            key = f"{base} #{n}"
        seen_keys.add(key)
        fixed.append((Party(key, p.lots, p.records) if key != p.key else p, g))

    anchor_addr = {_street_zip(a)[:2] for a in addresses(anchor_ids)}
    links: list[Link] = []
    for p, g in fixed:
        mine = [e for e in edges if e["toId"] in g]
        for kind in ("address", "name"):
            ks = [e for e in mine if e["type"] == f"CONNECTED_BY_{kind.upper()}"]
            if not ks:
                continue
            weight = max((e["weight"] for e in ks if e.get("weight") is not None), default=None)
            tail = f"{len(ks)} link{'s' if len(ks) != 1 else ''}" + (f", weight {weight:g}" if weight is not None else "")
            if kind == "address":
                theirs = addresses(g)
                shared = [a for a in theirs if _street_zip(a)[:2] in anchor_addr]
                ev = []
                for a in shared or theirs:
                    why = _mask_reason(a, masks)
                    text = (f"Business address as recorded on both parties: {a}. Joined by a shared business address ({tail})." if shared else
                            f"Business address as recorded on {p.key}: {a}. The method found a shared address; which string is not identified ({tail}).")
                    ev.append(Evidence("shared_address", text, SOURCE_HPD, setAside=why is not None, reason=why))
                links.append(Link(anchor, p, "address", tuple(ev)))
            else:
                rule = None
                for a_name in {recs[i]["name"] for i in anchor_ids if i in recs}:
                    for b_name in {recs[i]["name"] for i in g if i in recs}:
                        outcome, r = name_agreement(a_name, b_name)
                        rule = rule or r
                links.append(Link(anchor, p, "name", (Evidence(
                    "name_similarity", f"The network method linked the names {anchor.key} and {p.key} ({tail}).", SOURCE_NETWORK),), rule))
    anchor_names = sorted({recs[i]["name"].upper() for i in anchor_ids if i in recs})
    for p, g in fixed:
        regs = ig.shared_registrations(sorted({x.bbl for x in (*anchor.lots, *p.lots)}), anchor_names,
                                       sorted({recs[i]["name"].upper() for i in g if i in recs}))
        cut = cut or len(regs) >= MAX_REGISTRATION_ROWS
        if regs:
            links.append(Link(anchor, p, "contact", _registration_evidence(regs)))
    if any(e.kind == "shared_address" for ln in links for e in ln.evidence):
        caveats.append(CAVEAT_MASK_AS_SPELLED)
    if any(ln.kind == "contact" for ln in links):
        caveats.append(CAVEAT_REGISTRATION_NAMES)
    if cut:
        caveats.append(CAVEAT_CUT)
    return Inputs("ok", name, anchor, tuple(links), caveats=tuple(caveats))
