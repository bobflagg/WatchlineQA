"""Client for the Geosupport sidecar. Used by the agent and, later, the loaders.

Geosupport is NYC DCP's address standardizer. A typed address goes in; the city's own BBL and BIN, the canonical
street and, when the street is unknown, similar street names come out. The sidecar (geosupport/) passes
Geosupport's raw response through; every interpretation is here, where it is tested.

A resolved BBL is a candidate until the graph confirms it. Geosupport can answer with a lot the graph does not
hold, and an outage must never be reported as "address not found".
"""
import os
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import StrEnum

import httpx

REQUIRED_RELEASE = os.environ.get("GEOSUPPORT_RELEASE", "25b")  # pinned with geosupport/Dockerfile
URL = os.environ.get("GEOSUPPORT_URL", "http://localhost:8081")
MAX_CANDIDATES = 5
# Basis names, in the order Client.resolve() tries them. Any basis but AS_TYPED marks a resolved match as inferred.
AS_TYPED = "as_typed"
ORDINALS = "after_spelling_ordinals_as_digits"
MARKS = "after_removing_apostrophes"
ORDINALS_MARKS = "after_spelling_ordinals_as_digits_and_removing_apostrophes"
CANDIDATE = "after_taking_the_citys_spelling_of_the_street"
_NONE_BBL = "0000000000"


class Outcome(StrEnum):
    RESOLVED = "resolved"
    NO_TAX_LOT = "no_tax_lot"                    # address parses, no lot exists for it (GRC 00, empty BBL)
    STREET_AMBIGUOUS = "street_ambiguous"        # street unknown, the city offers similar names
    STREET_NOT_RECOGNIZED = "street_not_recognized"
    HOUSE_NUMBER_OUT_OF_RANGE = "house_number_out_of_range"
    INVALID_INPUT = "invalid_input"
    UNAVAILABLE = "unavailable"                  # sidecar down: never "not found"
    FAILED = "failed"                            # unrecognized return code; fails closed


@dataclass(frozen=True)
class Result:
    outcome: Outcome
    bbl: str | None = None
    bin: str | None = None            # None when Geosupport gives a placeholder (x000000): a lot with no building record
    billing_bbl: str | None = None    # condominium billing lot, when the address is a condo unit
    street: str | None = None         # the city's canonical street name
    house: str | None = None          # the house number as Geosupport returns it
    candidates: tuple[str, ...] = ()  # similar street names, capped
    candidate_total: int = 0
    grc: str | None = None
    message: str | None = None
    typed: str = ""                   # what was sent to Geosupport
    basis: str | None = None          # which spelling matched: as_typed or the repair that was applied
    inferred: bool = False            # True when a resolved match came from a variant, not the address as typed


def _text(response: dict, key: str) -> str | None:
    v = response.get(key)
    return re.sub(r"\s+", " ", v).strip() or None if isinstance(v, str) else None


def _bbl(value) -> str | None:
    flat = value.get("BOROUGH BLOCK LOT (BBL)") if isinstance(value, dict) else value
    flat = flat.strip() if isinstance(flat, str) else ""
    return None if not flat or flat == _NONE_BBL else flat


def interpret(response: dict, typed: str = "") -> Result:
    """Raw Geosupport response to a structured outcome. Pure."""
    grc = _text(response, "Geosupport Return Code (GRC)")
    message = _text(response, "Message")
    street = _text(response, "First Street Name Normalized")
    names = [str(n).strip() for n in (response.get("List of Street Names") or []) if str(n).strip()]
    house = _text(response, "House Number - Display Format")
    common = dict(grc=grc, message=message, street=street, house=house, typed=typed)
    if grc in ("00", "01"):  # 01 = success with a warning
        bbl = _bbl(response.get("BOROUGH BLOCK LOT (BBL)"))
        if not bbl:
            return Result(Outcome.NO_TAX_LOT, **common)
        bin_ = _text(response, "Building Identification Number (BIN) of Input Address or NAP")
        return Result(Outcome.RESOLVED, bbl=bbl, bin=None if not bin_ or re.fullmatch(r"[1-5]0{6}", bin_) else bin_,
                      billing_bbl=_bbl(response.get("Condominium Billing BBL")), **common)
    if grc == "EE" and names:
        return Result(Outcome.STREET_AMBIGUOUS, candidates=tuple(names[:MAX_CANDIDATES]), candidate_total=len(names), **common)
    if grc in ("EE", "11"):
        return Result(Outcome.STREET_NOT_RECOGNIZED, **common)
    if grc == "42":
        return Result(Outcome.HOUSE_NUMBER_OUT_OF_RANGE, **common)
    if grc == "13":
        return Result(Outcome.INVALID_INPUT, **common)
    return Result(Outcome.FAILED, **common)


# ---- cleaning what a person types ------------------------------------------------------------------------------

_MARKS = re.compile("[\u0027\u2018\u2019\u02bc\u0060\u00b4]")  # straight, curly and modifier apostrophes, grave, acute


_UNIT = re.compile(r"\b(?:APT|APARTMENT|UNIT|STE|SUITE|FL|FLOOR|RM|ROOM)\b\.?\s*[\w-]+|#\s*[\w-]+|\b(?:REAR|BSMT|BASEMENT)\b", re.I)
_ONES = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9,
         "TENTH": 10, "ELEVENTH": 11, "TWELFTH": 12, "THIRTEENTH": 13, "FOURTEENTH": 14, "FIFTEENTH": 15, "SIXTEENTH": 16,
         "SEVENTEENTH": 17, "EIGHTEENTH": 18, "NINETEENTH": 19}
_TENS = {"TWENTY": 20, "THIRTY": 30, "FORTY": 40, "FIFTY": 50, "SIXTY": 60, "SEVENTY": 70, "EIGHTY": 80, "NINETY": 90}
_TENTHS = {"TWENTIETH": 20, "THIRTIETH": 30, "FORTIETH": 40, "FIFTIETH": 50, "SIXTIETH": 60, "SEVENTIETH": 70,
           "EIGHTIETH": 80, "NINETIETH": 90}


def clean(house: str, street: str) -> tuple[str, str, list[str]]:
    """Strip unit and floor text from a typed address. Returns house, street and what was removed."""
    removed = []
    # The sidecar answers non-ASCII text with a 500, which would read as an outage: fold to ASCII first.
    house, street = (unicodedata.normalize("NFKD", _MARKS.sub("'", t)).encode("ascii", "ignore").decode() for t in (house, street))
    if "," in street:  # "10 Hallett's Pt, Astoria": the part after a comma is a locality hint, not the street
        street, locality = street.split(",", 1)
        removed.append(f"locality: {locality.strip()}")

    def cut(m):
        removed.append(m.group(0).strip())
        return " "

    street = _UNIT.sub(cut, street)
    house = _UNIT.sub(cut, house)
    street = re.sub(r"[.,]", " ", street)
    return re.sub(r"\s+", " ", house).strip(), re.sub(r"\s+", " ", street).strip(), removed


def spelled_ordinals_to_digits(street: str) -> str:
    """'Fifty-fourth Street' -> '54 Street'; 'West Tenth Street' -> 'West 10 Street'. Unchanged if none found."""
    words = re.split(r"[\s-]+", street.upper())
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in _TENS and i + 1 < len(words) and words[i + 1] in _ONES and _ONES[words[i + 1]] < 10:
            out.append(str(_TENS[w] + _ONES[words[i + 1]]))
            i += 2
        elif w in _TENTHS:
            out.append(str(_TENTHS[w]))
            i += 1
        elif w in _ONES:
            out.append(str(_ONES[w]))
            i += 1
        else:
            out.append(w)
            i += 1
    return " ".join(out)


def remove_apostrophes(street: str) -> str:
    """"Hallett's Point" -> "Halletts Point": the city's street names carry no apostrophe in this position."""
    return _MARKS.sub("", street)


def street_key(name: str) -> str:
    """Letters and digits only, upper case. Two spellings with the same key differ only in marks and spacing."""
    return re.sub(r"[^A-Z0-9]", "", name.upper())


# ---- the client --------------------------------------------------------------------------------------------------

class ReleaseMismatch(RuntimeError):
    """The sidecar runs a different Geosupport release than the one this project pins."""


class Client:
    """No retries: geocoding is deterministic, so a retry only slows an outage down."""

    def __init__(self, url: str = URL, timeout: float = 10.0, http: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self._http = http or httpx.Client(timeout=timeout)
        self._pinned = False

    def health(self) -> str:
        r = self._http.get(f"{self.url}/health")
        r.raise_for_status()
        try:
            body = r.json()
        except ValueError:
            body = None
        release = body.get("release") if isinstance(body, dict) else None
        if release != REQUIRED_RELEASE:
            raise ReleaseMismatch(f"sidecar runs {release}, project pins {REQUIRED_RELEASE}")
        return release

    def _pin_release(self) -> None:
        """Check the sidecar's release once per client. An outage raises httpx.HTTPError; a mismatch, ReleaseMismatch."""
        if not self._pinned:
            self.health()
            self._pinned = True

    def _raw(self, house: str, street: str, zip5: str | None, borough: str | None) -> dict:
        body = {"house_number": house, "street_name": street}
        body["zip_code" if zip5 else "borough"] = zip5 or borough
        r = self._http.post(f"{self.url}/resolve", json=body)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError:
            return {}  # not JSON: interpret() reports FAILED
        return data if isinstance(data, dict) else {}

    def resolve(self, house: str, street: str, zip5: str | None = None, borough: str | None = None) -> tuple[Result, list[str]]:
        """Resolve a typed address. Returns the result and every spelling tried, in order.

        Tries the address as typed (units removed), then the same with spelled-out ordinals as digits. Stops at the
        first spelling that resolves, has no tax lot, or is out of range for the house number. Otherwise every
        spelling is tried, and similar street names from any of them are returned as candidates.
        """
        house, street, _removed = clean(house, street)
        tried = [f"{house} {street}"]
        # (basis, street spelling). Each repair changes the street spelling only, never the house number or borough.
        variants = [(AS_TYPED, street)]
        for basis, v in ((ORDINALS, spelled_ordinals_to_digits(street)), (MARKS, remove_apostrophes(street)),
                         (ORDINALS_MARKS, spelled_ordinals_to_digits(remove_apostrophes(street)))):
            if all(v.upper() != seen.upper() for _, seen in variants):
                variants.append((basis, v))
        try:
            self._pin_release()
        except httpx.HTTPError as exc:
            return Result(Outcome.UNAVAILABLE, message=str(exc)[:120], typed=tried[0]), tried
        last = Result(Outcome.FAILED, typed=tried[0])
        basis = AS_TYPED
        names: list[str] = []
        queue = list(variants)
        while queue:
            basis, v = queue.pop(0)
            typed = f"{house} {v}"
            if typed not in tried:
                tried.append(typed)
            try:
                last = interpret(self._raw(house, v, zip5, borough), typed=typed)
            except httpx.HTTPError as exc:
                return Result(Outcome.UNAVAILABLE, message=str(exc)[:120], typed=typed), tried
            names += [n for n in last.candidates if n not in names]
            if last.outcome in (Outcome.RESOLVED, Outcome.NO_TAX_LOT, Outcome.HOUSE_NUMBER_OUT_OF_RANGE):
                break
            if not queue and basis != CANDIDATE and last.outcome in (Outcome.STREET_AMBIGUOUS, Outcome.STREET_NOT_RECOGNIZED):
                # Last repair: the city's own list holds exactly one street that differs from what was typed only in
                # marks or spacing. Several such names, or none, stay as candidates for a person to choose.
                keys = {street_key(x) for _, x in variants} | ({street_key(last.street)} if last.street else set())
                same = [n for n in names if street_key(n) in keys]
                if len(same) == 1 and f"{house} {same[0]}" not in tried:
                    queue.append((CANDIDATE, same[0]))
        if names and last.outcome in (Outcome.STREET_AMBIGUOUS, Outcome.STREET_NOT_RECOGNIZED):
            # similar names from any spelling tried, kept even if a later spelling says "not recognized"
            last = replace(last, outcome=Outcome.STREET_AMBIGUOUS, candidates=tuple(names[:MAX_CANDIDATES]),
                           candidate_total=len(names))
        return replace(last, basis=basis, inferred=basis != AS_TYPED and last.outcome is Outcome.RESOLVED), tried
