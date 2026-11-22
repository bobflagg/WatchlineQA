"""Agent settings. The model is a decision recorded in docs/status.md; change it with the AGENT_MODEL env var."""
import os

AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
