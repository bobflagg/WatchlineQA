import json

import httpx
import pytest
from neo4j.exceptions import ServiceUnavailable
from test_profile import BUILDINGS, FakePG, answer

from watchline.agent import tools as T
from watchline.agent.config import AGENT_MODEL
from watchline.geosupport.geosupport import Outcome, ReleaseMismatch, Result
from watchline.geosupport.resolution import Match
from watchline.profile.profile import build_profile


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.calls = []

    def resolve(self, house, street, zip5=None, borough=None):
        self.calls.append((house, street, zip5, borough))
        if self.error:
            raise self.error
        return self.result, [f"{house} {street}"]


class FakeGraph:
    def has_lot(self, bbl): return True
    def other_lots_on_bin(self, bin_, bbl): return []


def resolved():
    return Result(outcome=Outcome.RESOLVED, bbl="1000010001", bin="1", house="1", street="MAIN ST", typed="1 Main St",
                  grc="00")


def full_profile(buildings=BUILDINGS):
    pg = FakePG(buildings=buildings,
                violations=[dict(bin="1", violationClass="A", status="Close", n=2)],
                problems=[dict(bin="1", majorCategory="HEAT", duplicate=True, n=3)],
                litigation=[dict(bin="1", caseType="Tenant Action", caseStatus="CLOSED", harassmentFinding=None, n=1)])
    return build_profile(answer(), pg)


def test_default_model_is_haiku():
    assert AGENT_MODEL == "claude-haiku-5-5"


def test_profile_to_dict_is_json_safe_and_by_type():
    out = T.profile_to_dict(full_profile())
    json.dumps(out)                                              # no tuple keys, no dataclasses
    first = out["buildings"][0]
    assert first["violations"] == [{"violationClass": "A", "status": "Close", "n": 2}]
    assert first["problems"] == [{"majorCategory": "HEAT", "duplicate": True, "n": 3}]
    assert out["totals_across_all_listed_buildings"]["violations"] == first["violations"]
    assert out["lot"]["unitsRes"] == 24 and "unitsRes" not in first   # lot-wide stays on the lot


def test_unresolved_profile_has_no_lot_or_buildings():
    p = build_profile(answer(outcome=Match.NOT_FOUND, bbl=None, in_graph=None, grc="11"), FakePG())
    out = T.profile_to_dict(p)
    assert out["lot"] is None and out["buildings"] == [] and out["caveats"]


def test_buildings_capped_and_addressed_building_always_shown():
    many = [dict(bin=str(i), address=f"{i} MAIN ST") for i in range(2, 40)] + [dict(bin="1", address="1 MAIN ST")]
    out = T.profile_to_dict(full_profile(many), max_buildings=5)
    assert len(out["buildings"]) == 5 and out["buildings"][0]["bin"] == "1" and out["buildings"][0]["addressed"]
    assert out["buildings_listed"] == 39 and out["buildings_listed_is_lower_bound"] is False
    assert T.CAVEAT_BUILDINGS_CAPPED.format(shown=5, total=39) in out["caveats"]
    assert "will not equal the sum of the rows shown" in " ".join(out["caveats"])


def test_totals_cover_all_listed_buildings_not_just_those_shown():
    many = [dict(bin=str(i), address=f"{i} MAIN ST") for i in range(2, 12)] + [dict(bin="1", address="1 MAIN ST")]
    pg = FakePG(buildings=many, violations=[dict(bin=str(i), violationClass="A", status="Open", n=1) for i in range(2, 12)])
    out = T.profile_to_dict(build_profile(answer(), pg), max_buildings=3)
    shown = sum(v["n"] for b in out["buildings"] for v in b["violations"])
    total = sum(v["n"] for v in out["totals_across_all_listed_buildings"]["violations"])
    assert shown < total == 10


def test_listed_count_flags_the_graph_row_limit():
    from watchline.profile.profile import MAX_BUILDINGS
    full = [dict(bin=str(i), address=f"{i} MAIN ST") for i in range(MAX_BUILDINGS)]
    out = T.profile_to_dict(build_profile(answer(bin="0"), FakePG(buildings=full)))
    assert out["buildings_listed_is_lower_bound"] is True and any("truncated" in c for c in out["caveats"])


def test_harassment_count_is_labelled_and_counts_only_findings():
    pg = FakePG(buildings=BUILDINGS, litigation=[
        dict(bin="1", caseType="HP", caseStatus="CLOSED", harassmentFinding="After Inquest", n=1),
        dict(bin="1", caseType="HP", caseStatus="CLOSED", harassmentFinding="After Trial", n=2),
        dict(bin="1", caseType="HP", caseStatus="CLOSED", harassmentFinding="No Harassment", n=5),
        dict(bin="1", caseType="HP", caseStatus="OPEN", harassmentFinding=None, n=7)])
    first = T.profile_to_dict(build_profile(answer(), pg))["buildings"][0]
    assert first["harassment_findings_after_inquest_or_trial"] == 3
    assert "harassment_findings" not in first


def make_tool(client):
    return T.make_building_profile_tool(client, FakeGraph(), FakePG(buildings=BUILDINGS))


def test_tool_name_and_description_for_the_model():
    tool = make_tool(FakeClient(resolved()))
    assert tool.name == "building_profile"
    assert "street address" in tool.description and "caveats" in tool.description
    assert set(tool.args) == {"address", "borough", "zip_code"}


def test_tool_returns_ok_profile():
    out = make_tool(FakeClient(resolved())).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "ok" and out["resolution"]["bbl"] == "1000010001"


def test_missing_borough_is_an_answer_not_an_exception():
    out = make_tool(FakeClient(resolved())).invoke({"address": "1 Main St"})
    assert out["status"] == "needs_borough" and "do not guess" in out["message"]


def test_unparseable_text_is_invalid_input():
    out = make_tool(FakeClient(resolved())).invoke({"address": "next to the park", "borough": "Queens"})
    assert out["status"] == "invalid_input"


@pytest.mark.parametrize("error", [ServiceUnavailable("down"), httpx.ConnectError("refused")])
def test_infrastructure_errors_are_reported_as_outage(error):
    tool = T.make_building_profile_tool(FakeClient(resolved()), FakeGraph(), _RaisingPG(error))
    out = tool.invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "error" and "not an answer about the address" in out["message"]


class _RaisingPG(FakePG):
    def __init__(self, error):
        super().__init__(buildings=BUILDINGS)
        self.error = error

    def lot(self, bbl):
        raise self.error


def test_unavailable_geosupport_is_an_error_status_not_ok():
    unavailable = Result(outcome=Outcome.UNAVAILABLE, message="connection refused", typed="1 Main St")
    out = make_tool(FakeClient(unavailable)).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "error" and out["resolution"]["outcome"] == "unavailable"
    assert any("outage" in c for c in out["caveats"])


@pytest.mark.parametrize("error", [ReleaseMismatch("sidecar runs 24d, project pins 25b"), KeyError("yearBuilt"),
                                   TypeError("bad body"), RuntimeError("anything")])
def test_any_other_exception_is_an_error_answer_without_a_stack_trace(error):
    out = make_tool(FakeClient(error=error)).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "error" and type(error).__name__ in out["message"] and "do not guess" in out["message"]


def test_serialization_failure_is_an_error_answer(monkeypatch):
    monkeypatch.setattr(T, "profile_to_dict", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    out = make_tool(FakeClient(resolved())).invoke({"address": "1 Main St", "borough": "Manhattan"})
    assert out["status"] == "error"          # not mislabelled invalid_input


def test_integer_zip_is_accepted_and_passed_as_text():
    client = FakeClient(resolved())
    out = make_tool(client).invoke({"address": "1 Main St", "zip_code": 11220})
    assert out["status"] == "ok" and client.calls[0][2] == "11220"


# ---- the ontology check used by the evals must actually reject violations -------------------------------------

def _good_output():
    return T.profile_to_dict(full_profile())


def test_ontology_check_accepts_a_good_output():
    from test_eval_q01 import check_ontology
    check_ontology(_good_output())


@pytest.mark.parametrize("mutate", [
    lambda o: o.__setitem__("total_violations", 5),                                             # a summed score
    lambda o: o["buildings"][0].__setitem__("unitsRes", 24),                                    # lot-wide on a building
    lambda o: o["buildings"][0]["violations"].append({"n": 9}),                                 # a bare number, no class
    lambda o: o["totals_across_all_listed_buildings"]["violations"].__setitem__(0, {"violationClass": "A", "status": "Close", "n": 99}),
    lambda o: o["counts"][0].__setitem__("source", ""),                                         # a count with no source
    lambda o: o["caveats"].clear(),                                                             # fault caveat dropped
])
def test_ontology_check_rejects_violations(mutate):
    from test_eval_q01 import check_ontology
    out = _good_output()
    mutate(out)
    with pytest.raises(AssertionError):
        check_ontology(out)
