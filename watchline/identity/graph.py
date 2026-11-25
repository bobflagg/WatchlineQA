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

CAVEAT_CUT = Caveat("identity_party_cut", "A party or the list of candidate parties was cut at a size limit, so the portfolio may be incomplete.")
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


def _closure(ig: IdentityGraph, seed: set[int]) -> tuple[set[int], bool]:
    """The records joined to the seed by identity edges, and whether the size or round limit cut it."""
    seen, frontier = set(seed), set(seed)
    for _ in range(MAX_ROUNDS):
        if not frontier:
            return seen, False
        new = {r["peerId"] for r in ig.identity_pairs(sorted(frontier))} - seen
        seen |= new
        frontier = new
        if len(seen) >= MAX_RECORDS:
            return seen, True
    return seen, bool(frontier)


def _party(key: str, ids: set[int], recs: dict[int, dict], lots: list[dict]) -> Party:
    by_bbl: dict[str, Lot] = {}
    for r in lots:
        if r["nodeId"] in ids:
            by_bbl.setdefault(r["bbl"], Lot(r["bbl"], r.get("unitsRes")))
    return Party(key, tuple(sorted(by_bbl.values(), key=lambda x: x.bbl)), records=len(ids))


def _key(ids: set[int], recs: dict[int, dict]) -> str:
    return " / ".join(sorted({recs[i]["name"] for i in ids if i in recs}))


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
        cands = tuple(sorted((_key(g, recs), len(_party("", g, recs, lots).lots)) for g in groups))
        return Inputs("ambiguous_name", name, candidates=cands, caveats=tuple(caveats))

    anchor_ids = groups[0]
    edges = ig.lead_edges(sorted(anchor_ids))
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
    for p, g in sorted(parties, key=lambda t: (t[0].key, t[0].lots[0].bbl if t[0].lots else "")):
        if p.key in seen_keys:                                   # same name on a different group: tell them apart by a lot, not an id
            p = Party(f"{p.key} [lot {p.lots[0].bbl if p.lots else 'none'}]", p.lots, p.records)
        seen_keys.add(p.key)
        fixed.append((p, g))

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
    if any(e.kind == "shared_address" for ln in links for e in ln.evidence):
        caveats.append(CAVEAT_MASK_AS_SPELLED)
    if cut:
        caveats.append(CAVEAT_CUT)
    return Inputs("ok", name, anchor, tuple(links), caveats=tuple(caveats))
