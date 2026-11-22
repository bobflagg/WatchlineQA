"""Q1.3: turn a typed address into the answer contract.

    {input, outcome, bbl, bin, inGraph, relatedLots, candidates, grc, message, tried}

outcome is one of exact / variant / ambiguous / not_found (specs/questions/q01.md), plus `unavailable` when the
Geosupport service could not be reached. `unavailable` is an outage, never an answer about the address.

Geosupport decides the outcome. The graph only says whether the BBL it returned is a Lot we hold (inGraph) and
which other Lots share its BIN (relatedLots, for example the second lot of a condominium building).
"""
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import yaml
from neo4j import Driver, RoutingControl

from .geosupport import Client, Outcome, Result, clean, street_key


class Match(StrEnum):
    EXACT = "exact"
    VARIANT = "variant"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip().upper()


def classify(r: Result) -> Match:
    """Geosupport result to outcome. Pure. exact means the returned house and street equal the typed ones after
    case and whitespace only; a warning (GRC 01) or a respelled retry makes it a variant."""
    if r.outcome is Outcome.UNAVAILABLE:
        return Match.UNAVAILABLE
    if r.outcome is Outcome.STREET_AMBIGUOUS:
        return Match.AMBIGUOUS
    if r.outcome is Outcome.RESOLVED:
        same = _norm(f"{r.house} {r.street}") == _norm(r.typed)
        return Match.EXACT if same and not r.inferred and r.grc == "00" else Match.VARIANT
    return Match.NOT_FOUND


class Graph(Protocol):
    def has_lot(self, bbl: str) -> bool: ...
    def other_lots_on_bin(self, bin_: str, bbl: str) -> list[str]: ...


class Neo4jGraph:
    """Read-only lookups in the watchline graph."""

    def __init__(self, driver: Driver, database: str):
        self._driver, self._db = driver, database

    def _read(self, query: str, **params):
        return self._driver.execute_query(query, params, database_=self._db, routing_=RoutingControl.READ).records

    def has_lot(self, bbl: str) -> bool:
        return bool(self._read("MATCH (l:Lot {bbl: $bbl}) RETURN l.bbl AS bbl", bbl=bbl))

    def other_lots_on_bin(self, bin_: str, bbl: str) -> list[str]:
        rows = self._read("MATCH (l:Lot)-[:HAS_BUILDING]->(:Building {bin: $bin}) WHERE l.bbl <> $bbl "
                          "RETURN l.bbl AS bbl ORDER BY bbl", bin=bin_, bbl=bbl)
        return [r["bbl"] for r in rows]


@dataclass(frozen=True)
class Answer:
    input: str
    outcome: Match
    bbl: str | None = None
    bin: str | None = None
    in_graph: bool | None = None            # None when there is no BBL to look up
    related_lots: tuple[str, ...] = ()      # other graph Lots that share the BIN
    candidates: tuple[str, ...] = ()        # similar street names, for ambiguous
    grc: str | None = None
    message: str | None = None
    tried: tuple[str, ...] = ()             # every spelling sent to Geosupport
    inferred: bool = False                  # the lot came from a respelled address, not the one typed
    borough_inferred_from: str | None = None  # resolve_text: the neighborhood the borough was taken from (never exact)
    returned: str | None = None             # house and street as Geosupport returned them (what a variant matched)


def resolve_address(client: Client, graph: Graph, house: str, street: str, *,
                    borough: str | None = None, zip5: str | None = None) -> Answer:
    result, tried = client.resolve(house, street, zip5=zip5, borough=borough)
    outcome = classify(result)
    in_graph, related = None, ()
    if result.bbl:
        in_graph = graph.has_lot(result.bbl)
        if result.bin:
            related = tuple(graph.other_lots_on_bin(result.bin, result.bbl))
    return Answer(input=f"{house} {street}", outcome=outcome, bbl=result.bbl, bin=result.bin, in_graph=in_graph,
                  related_lots=related, candidates=result.candidates, grc=result.grc, message=result.message,
                  tried=tuple(tried), inferred=result.inferred,
                  returned=f"{result.house} {result.street}" if result.house and result.street else None)


# ---- an address typed as one string ------------------------------------------------------------------------------

class BoroughRequired(ValueError):
    """The text names no borough or ZIP, and none was given. Geosupport needs one: ask, never guess."""


_BOROUGHS = {"MANHATTAN": "Manhattan", "BROOKLYN": "Brooklyn", "QUEENS": "Queens", "BRONX": "Bronx", "THE BRONX": "Bronx",
             "STATEN ISLAND": "Staten Island", "NEW YORK": "Manhattan"}  # "New York" only as a comma part, never trailing text
_HOUSE = re.compile(r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?$")  # 218, 5413A, Queens 37-20
_ZIP = re.compile(r"^(?:NY\s+)?(\d{5})(?:-\d{4})?$|^NY$", re.I)


@dataclass(frozen=True)
class Parsed:
    house: str
    street: str
    borough: str | None = None
    zip5: str | None = None
    locality: tuple[str, ...] = ()   # comma parts that are neither borough nor ZIP, e.g. a neighborhood; never used to look up


def parse_address(text: str) -> Parsed:
    """Split 'house street[, locality][, borough][, NY zip]' (or a trailing borough or ZIP without commas). Pure.
    A neighborhood is kept as `locality` and not turned into a borough. Raises ValueError when no house number leads."""
    first, *rest = [clean("", part)[1] for part in text.split(",")]  # per part: units, periods and non-ASCII handled
    borough = zip5 = None
    locality: list[str] = []
    for part in rest:
        m = _ZIP.match(part)
        if m:
            zip5 = m.group(1) or zip5
        elif part.upper() in _BOROUGHS:
            borough = _BOROUGHS[part.upper()]
        elif part:
            locality.append(part)
    tokens = first.split()
    if not rest:  # no commas: take a trailing ZIP, then a trailing borough, but never the whole street
        if len(tokens) > 2 and re.fullmatch(r"\d{5}", tokens[-1]):
            zip5 = tokens.pop()
        for name in sorted(_BOROUGHS, key=len, reverse=True):
            n = name.split()
            if name != "NEW YORK" and len(tokens) > len(n) + 1 and [t.upper() for t in tokens[-len(n):]] == n:
                borough = _BOROUGHS[name]
                tokens = tokens[:-len(n)]
                break
    if len(tokens) < 2 or not _HOUSE.match(tokens[0]):
        raise ValueError(f"no house number and street in {text!r}")
    return Parsed(tokens[0], " ".join(tokens[1:]), borough, zip5, tuple(locality))


_NEIGHBORHOODS: dict[str, set[str]] | None = None


def boroughs_of(name: str) -> set[str]:
    """Boroughs that list this neighborhood in data/neighborhoods.yaml (curated). Empty set when unknown."""
    global _NEIGHBORHOODS
    if _NEIGHBORHOODS is None:
        table = yaml.safe_load((Path(__file__).resolve().parent / "neighborhoods.yaml").read_text())
        _NEIGHBORHOODS = {}
        for borough, names in table.items():
            for n in names:
                _NEIGHBORHOODS.setdefault(street_key(n), set()).add(borough)
    return _NEIGHBORHOODS.get(street_key(name), set())


def resolve_text(client: Client, graph: Graph, text: str, *, borough: str | None = None, zip5: str | None = None) -> Answer:
    """Resolve an address typed as one string.

    Borough order: the argument, the text, then a neighborhood in the text (data/neighborhoods.yaml, curated). A neighborhood
    is used only when it names exactly one borough; the answer then says so (`borough_inferred_from`) and is never `exact`.
    Raises ValueError when borough, ZIP or neighborhood disagree, and BoroughRequired when no single borough or ZIP results
    (none given, an unknown neighborhood, or one that spans boroughs): ask, never guess."""
    p = parse_address(text)
    for given, found, what in ((borough, p.borough, "borough"), (zip5, p.zip5, "ZIP")):
        if given and found and _norm(given) != _norm(found):
            raise ValueError(f"{what} {given!r} given, but the text says {found!r}")
    borough, zip5 = borough or p.borough, zip5 or p.zip5
    hood = None
    if not zip5:
        hoods = {n: boroughs_of(n) for n in p.locality if boroughs_of(n)}
        if borough and hoods and not any(_norm(borough) in {_norm(b) for b in bs} for bs in hoods.values()):
            raise ValueError(f"borough {borough!r}, but {', '.join(hoods)} is in {sorted(set().union(*hoods.values()))}")
        if not borough and hoods:
            found = set().union(*hoods.values())
            if len(found) == 1:
                borough, hood = next(iter(found)), ", ".join(hoods)
            else:
                raise BoroughRequired(f"{', '.join(hoods)} is in more than one borough: {sorted(found)}")
    if not borough and not zip5:
        raise BoroughRequired(f"{text!r} names no borough or ZIP")
    ans = resolve_address(client, graph, p.house, p.street, borough=borough, zip5=zip5)
    if hood:
        ans = replace(ans, borough_inferred_from=hood, outcome=Match.VARIANT if ans.outcome is Match.EXACT else ans.outcome)
    return ans
