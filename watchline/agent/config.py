"""Agent settings. Models are decisions recorded in docs/status.md; change them with env vars.

Two API keys, so spend can be told apart in the Anthropic Console and an eval can never run on the product's key:
- AGENT_ANTHROPIC_API_KEY: the agent in `make chat`, `make ui` and the notebooks.
- EVAL_ANTHROPIC_API_KEY: the eval runner (`make eval-agent`): the agent under test and the judge.
The generic ANTHROPIC_API_KEY is never read by our code.
"""
import os

AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-haiku-5-5")   # grades agent-level evals; raise it if it proves lenient
AGENT_KEY_ENV = "AGENT_ANTHROPIC_API_KEY"
EVAL_KEY_ENV = "EVAL_ANTHROPIC_API_KEY"
REQUEST_TIMEOUT_S = 60.0     # one HTTP request to the API; a hung connection ends here rather than waiting forever


class MissingKey(RuntimeError):
    """The environment variable that holds an API key is unset. The message names the variable, never a value."""


def api_key(env_name: str) -> str:
    key = os.environ.get(env_name)
    if not key:
        raise MissingKey(f"{env_name} is not set (put it in .env; see .env.example).")
    return key


def make_model(model_id: str, key_env: str, **kwargs):
    """A ChatAnthropic that uses the key named by `key_env` and no other."""
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model_id, api_key=api_key(key_env), timeout=REQUEST_TIMEOUT_S, **kwargs)


def agent_model():
    return make_model(AGENT_MODEL, AGENT_KEY_ENV)


def eval_agent_model():
    return make_model(AGENT_MODEL, EVAL_KEY_ENV)


def eval_judge_model():
    return make_model(JUDGE_MODEL, EVAL_KEY_ENV, max_tokens=2000)
