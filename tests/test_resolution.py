import os

import httpx
import pytest
from dotenv import load_dotenv
from neo4j import GraphDatabase

from watchline.geosupport.geosupport import Client, Outcome, Result
from watchline.geosupport.resolution import Match, Neo4jGraph, resolve_address

load_dotenv()


class FakeClient:
    def __init__(self, result: Result, tried: list[str] | None = None):
        self.result, self.tried = result, tried or ["1 MAIN ST"]
        self.calls = []

    def resolve(self, house, street, zip5=None, borough=None):
        self.calls.append((house, street, zip5, borough))
        return self.result, self.tried


class FakeGraph:
    def __init__(self, lots=(), others=()):
        self.lots, self.others = set(lots), list(others)
        self.other_calls = []

    def has_lot(self, bbl):
        return bbl in self.lots

    def other_lots_on_bin(self, bin_, bbl):
        self.other_calls.append((bin_, bbl))
        return self.others


def resolved(**kw):
    base = dict(outcome=Outcome.RESOLVED, bbl="1000010001", bin="1000001", house="1", street="MAIN ST",
                typed="1 Main St", grc="00")
    return Result(**{**base, **kw})


def test_exact_in_graph_with_related_lots():
    client = FakeClient(resolved())
    graph = FakeGraph(lots={"1000010001"}, others=["1000010002"])
    ans = resolve_address(client, graph, "1", "Main St", borough="1", zip5="10001")
    assert client.calls == [("1", "Main St", "10001", "1")]
    assert ans.input == "1 Main St"
    assert ans.outcome is Match.EXACT
    assert ans.bbl == "1000010001" and ans.bin == "1000001"
    assert ans.in_graph is True
    assert ans.related_lots == ("1000010002",)
    assert ans.tried == ("1 MAIN ST",)
    assert graph.other_calls == [("1000001", "1000010001")]


def test_resolved_but_lot_not_in_graph():
    ans = resolve_address(FakeClient(resolved()), FakeGraph(), "1", "Main St")
    assert ans.in_graph is False
    assert ans.related_lots == ()


def test_resolved_without_bin_skips_related_lookup():
    graph = FakeGraph(lots={"1000010001"}, others=["x"])
    ans = resolve_address(FakeClient(resolved(bin=None)), graph, "1", "Main St")
    assert ans.in_graph is True
    assert ans.related_lots == ()
    assert graph.other_calls == []


def test_variant_when_warning_or_inferred():
    warn = resolve_address(FakeClient(resolved(grc="01")), FakeGraph(), "1", "Main St")
    assert warn.outcome is Match.VARIANT and warn.grc == "01"
    inf = resolve_address(FakeClient(resolved(inferred=True)), FakeGraph(), "1", "Main St")
    assert inf.outcome is Match.VARIANT and inf.inferred is True


def test_ambiguous_returns_candidates_and_no_lookup():
    res = Result(outcome=Outcome.STREET_AMBIGUOUS, candidates=("MAIN ST", "MAIN AVE"), grc="42")
    graph = FakeGraph()
    ans = resolve_address(FakeClient(res), graph, "1", "Mian")
    assert ans.outcome is Match.AMBIGUOUS
    assert ans.candidates == ("MAIN ST", "MAIN AVE")
    assert ans.bbl is None and ans.in_graph is None
    assert graph.other_calls == []


def test_not_found():
    res = Result(outcome=Outcome.NO_TAX_LOT, message="no lot")
    ans = resolve_address(FakeClient(res), FakeGraph(), "999", "Main St")
    assert ans.outcome is Match.NOT_FOUND
    assert ans.in_graph is None and ans.message == "no lot"


def test_unavailable_is_not_not_found():
    ans = resolve_address(FakeClient(Result(outcome=Outcome.UNAVAILABLE)), FakeGraph(), "1", "Main St")
    assert ans.outcome is Match.UNAVAILABLE
    assert ans.in_graph is None


# ---- integration: real Geosupport sidecar and real Neo4j graph (credentials in .env) --------------------------------



@pytest.fixture(scope="module")
def live_client():
    client = Client()
    try:
        client.health()
    except httpx.HTTPError:
        pytest.skip(f"Geosupport sidecar not reachable at {client.url}")
    return client


@pytest.fixture(scope="module")
def live_graph():
    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))
    if not (uri and user and pw):
        pytest.skip("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.skip(f"Neo4j not reachable: {exc}")
    yield Neo4jGraph(driver, os.environ["NEO4J_DATABASE"])
    driver.close()


def test_live_exact_address(live_client, live_graph):
    ans = resolve_address(live_client, live_graph, "1", "Centre Street", borough="1")  # Manhattan Municipal Building
    assert ans.outcome is Match.EXACT
    assert ans.bbl == "1001210001" and ans.bin == "1001394"
    assert ans.inferred is False and ans.grc == "00"
    assert ans.tried == ("1 Centre Street",)
    assert isinstance(ans.in_graph, bool)  # answered by the real graph
    assert ans.in_graph == live_graph.has_lot(ans.bbl)


def test_live_variant_when_street_is_normalized(live_client, live_graph):
    ans = resolve_address(live_client, live_graph, "350", "5th Avenue", borough="1")  # Empire State Building
    assert ans.outcome is Match.VARIANT  # Geosupport returns "5 AVENUE", not "5TH AVENUE"
    assert ans.bbl == "1008350041"
    assert ans.in_graph == live_graph.has_lot(ans.bbl)
