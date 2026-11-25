"""Tests never send traces anywhere, whatever .env says (the fast tests use scripted models and fakes)."""
import os
from pathlib import Path

import pytest

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

RESULTS_DIR = Path(__file__).resolve().parent.parent / "build" / "agent-eval"
_GUARDS: list = []     # the run's guard, kept for the closing summary


@pytest.fixture(scope="session")
def eval_guard():
    """One cost guard for the whole eval run (all of Q1, Q2 and Q3), so EVAL_MAX_USD caps the run, not each file."""
    from watchline.agent.config import AGENT_MODEL
    from watchline.evals.guard import EvalGuard
    guard = EvalGuard.from_env(AGENT_MODEL, out_dir=RESULTS_DIR)
    _GUARDS.append(guard)
    yield guard
    guard.write()


def pytest_report_header(config):
    from watchline.evals.guard import DEFAULT_MAX_USD, env_float
    return f"eval spend cap EVAL_MAX_USD=${env_float('EVAL_MAX_USD', DEFAULT_MAX_USD):.2f} (applies to live model tests only)"


def pytest_terminal_summary(terminalreporter):
    from test_agent_eval_q01 import USE_JUDGE  # what the tests decided at import, not a fresh env read
    for guard in _GUARDS:
        terminalreporter.write_sep("-", "estimated model spend (see build/agent-eval/usage-*.json)")
        terminalreporter.write_line(f"Judge: {'ON' if USE_JUDGE else 'off'}   max calls/case: {guard.max_calls}")
        terminalreporter.write_line(guard.summary())


@pytest.fixture(scope="session")
def live_graph():
    """A read-only identity graph on the live Neo4j (no model); skips when the database is not reachable."""
    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    from watchline.identity.graph import Neo4jIdentityGraph
    load_dotenv()
    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))
    if not (uri and user and pw):
        pytest.skip("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.skip(f"Neo4j not reachable: {exc}")
    yield Neo4jIdentityGraph(driver, os.environ["NEO4J_DATABASE"])
    driver.close()


@pytest.fixture(scope="session")
def live_report_deps():
    """Everything the report reads, on the live Neo4j and the Geosupport sidecar (no model); skips when either is not reachable."""
    import httpx
    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    from watchline.deeds.timeline import Neo4jTimelineGraph
    from watchline.geosupport.geosupport import Client
    from watchline.geosupport.resolution import Neo4jGraph
    from watchline.identity.graph import Neo4jIdentityGraph
    from watchline.profile.profile import Neo4jProfileGraph
    from watchline.report.graph import ReportDeps
    load_dotenv()
    client = Client()
    try:
        client.health()
    except httpx.HTTPError:
        pytest.skip(f"Geosupport sidecar not reachable at {client.url}")
    uri, user, pw = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"))
    if not (uri and user and pw):
        pytest.skip("NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(user, pw))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.skip(f"Neo4j not reachable: {exc}")
    db = os.environ["NEO4J_DATABASE"]
    yield ReportDeps(client, Neo4jGraph(driver, db), Neo4jProfileGraph(driver, db), Neo4jTimelineGraph(driver, db), Neo4jIdentityGraph(driver, db))
    driver.close()
