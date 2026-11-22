"""Agent settings. Models are decisions recorded in docs/status.md; change them with env vars."""
import os

AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-haiku-5-5")   # grades agent-level evals; raise it if it proves lenient
