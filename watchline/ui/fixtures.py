"""Hand-built answers, one per kind, for looking at the page without the model, the graph or the sidecar."""
from watchline.agent.answer import Answer, CaveatOut, Evidence, Fact

_BUILDING = {"bin": "3000001", "address": "1 Example Street", "violations_by_class": {"A": 2, "B": 5, "C": 1}}
_CAVEATS = [
    CaveatOut(code="violations-cited", text="Violations are what was cited, not findings of fault."),
    CaveatOut(code="lot-wide", text="Units and assessed value belong to the lot, not to any one building."),
    CaveatOut(code="hpd-only", text="Violations exist only for HPD-registered buildings; none recorded is not a clean record."),
]

FIXTURES: dict[str, Answer] = {
    "profile": Answer(
        kind="profile", summary="The lot at 1 Example Street, Brooklyn has one registered building with 8 violations cited.",
        facts=[Fact(statement="The building has 2 class A, 5 class B and 1 class C violations cited.",
                    evidence=[Evidence(section="buildings", bin="3000001", bbl="3000010001", data=_BUILDING)]),
               Fact(statement="The lot has 12 residential units.",
                    evidence=[Evidence(section="characteristics", bbl="3000010001", data={"unitsRes": 12})])],
        caveats=_CAVEATS, sources=["HPD violations, release 26v1", "PLUTO 25b"]),
    "caveats": Answer(
        kind="profile", summary="One building is listed. A fact points at data the tools did not return.",
        facts=[Fact(statement="The building has open litigation.", unresolved=[{"section": "counts"}])],
        caveats=_CAVEATS, sources=["HPD litigation, release 26v1"]),
    "empty": Answer(kind="profile", summary="The lot is not HPD-registered, so no buildings or violations are listed."),
    "clarification": Answer(kind="clarification", summary="Which borough is 1 Example Street in?",
                            caveats=[], sources=[]),
    "not_found": Answer(kind="not_found", summary="No tax lot matched that address."),
    "refusal": Answer(kind="refusal", summary="The records cannot say whether a landlord is at fault; they show what was cited."),
    "error": Answer(kind="error", summary="The lookup failed. Nothing was answered; try again."),
}
