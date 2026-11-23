"""Name and address comparison rules for Q3 (decisions of 2026-11-12). Pure strings, computed at answer time, never stored.

N1: uppercase, trim, collapse whitespace. N2: N1, then remove periods and turn commas into spaces. Spaces inside a name are
never removed, so "K S TURNPIKE LLC" and "KS Turnpike LLC" stay different. A1: same street line (N1) and same first five ZIP digits.
Agreement is a comparison of recorded strings, not a finding that two records are the same party.
"""


def n1(s: str) -> str:
    return " ".join(s.upper().split())


def n2(s: str) -> str:
    return n1(s.replace(".", "").replace(",", " "))


def name_agreement(a: str | None, b: str | None) -> tuple[str, str | None]:
    """(outcome, rule). An absent or blank name on either side is not comparable."""
    if not (a and a.strip() and b and b.strip()):
        return "not_comparable", None
    if n1(a) == n1(b):
        return "exact_normalized", "N1"
    if n2(a) == n2(b):
        return "normalization_match", "N2"
    return "different", None


def _zip5(z: str | None) -> str | None:
    z = (z or "").strip()[:5]
    return z or None


def address_agreement(street_a: str | None, zip_a: str | None, street_b: str | None, zip_b: str | None) -> str:
    """same, differs or absent. Absent when either side lacks its street line or its ZIP: sameness cannot be shown either way."""
    if not (street_a and street_a.strip() and street_b and street_b.strip()) or not (_zip5(zip_a) and _zip5(zip_b)):
        return "absent"
    return "same" if n1(street_a) == n1(street_b) and _zip5(zip_a) == _zip5(zip_b) else "differs"
