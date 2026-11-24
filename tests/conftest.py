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
    for guard in _GUARDS:
        terminalreporter.write_sep("-", "estimated model spend (see build/agent-eval/usage-*.json)")
        terminalreporter.write_line(guard.summary())
