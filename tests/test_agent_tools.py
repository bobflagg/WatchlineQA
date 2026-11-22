import json

import httpx
import pytest
from neo4j.exceptions import ServiceUnavailable
from test_profile import BUILDINGS, FakePG, answer

from watchline.agent import tools as T
from watchline.agent.config import AGENT_MODEL
from watchline.geosupport.geosupport import Outcome, Result
from watchline.geosupport.resolution import Match
from watchline.profile.profile import build_profile


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def resolve(self, house, street, zip5=None, borough=None):
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
    assert out["lot_totals"]["violations"] == first["violations"]
    assert out["lot"]["unitsRes"] == 24 and "unitsRes" not in first   # lot-wide stays on the lot


def test_unresolved_profile_has_no_lot_or_buildings():
    p = build_profile(answer(outcome=Match.NOT_FOUND, bbl=None, in_graph=None, grc="11"), FakePG())
    out = T.profile_to_dict(p)
    assert out["lot"] is None and out["buildings"] == [] and out["caveats"]


def test_buildings_capped_and_addressed_building_always_shown():
    many = [dict(bin=str(i), address=f"{i} MAIN ST") for i in range(2, 40)] + [dict(bin="1", address="1 MAIN ST")]
    out = T.profile_to_dict(full_profile(many), max_buildings=5)
    assert len(out["buildings"]) == 5 and out["buildings"][0]["bin"] == "1" and out["buildings"][0]["addressed"]
    assert out["buildings_listed"] == 39
    assert T.CAVEAT_BUILDINGS_CAPPED.format(shown=5, total=39) in out["caveats"]


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
