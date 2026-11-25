"""The Watchline agent: a Deep Agent with its lookup tools and the ontology rules in its system prompt.

Deep Agents ships file tools, a shell tool and a subagent tool by default. None belong in a read-only records assistant,
so they are removed from what the model is offered (a harness profile) and, as a second layer, file reads and writes are
denied. The backend stays the in-memory default, so no repo file is reachable either way.
"""
from pathlib import Path

from deepagents import (
    FilesystemPermission,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact
from watchline.agent.config import agent_model
from watchline.agent.repeat_guard import RepeatGuardMiddleware
from watchline.agent.tools import (
    make_building_contacts_tool,
    make_building_profile_tool,
    make_deed_timeline_tool,
    make_deed_vs_owner_tool,
    make_registered_owner_tool,
)

PROMPTS = Path(__file__).parent / "prompts"
BUILTIN_TOOLS = frozenset({"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute", "task",
                           "write_todos"})


def system_prompt() -> str:
    """system.md with the ontology rules (the single source also imported by CLAUDE.md) filled in."""
    rules = (PROMPTS / "ontology_rules.md").read_text().strip()
    return (PROMPTS / "system.md").read_text().replace("{ontology_rules}", rules)


def memory_checkpointer() -> InMemorySaver:
    """An in-memory conversation store that may hold the structured answer. Without the allowlist, LangGraph warns that it will
    block deserializing our types in a future version."""
    allowed = [("watchline.agent.answer", t.__name__) for t in (ModelAnswer, ModelFact, EvidenceRef)]
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


def _lock_down() -> None:
    """Offer the model only our tools. Registered under the provider name, so it covers any anthropic model in this process.

    The registry is process-wide and merges, so this affects every Anthropic Deep Agent built in the process.
    """
    register_harness_profile("anthropic", HarnessProfile(
        excluded_tools=BUILTIN_TOOLS, general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))


def build_agent(client, graph, pg, rg=None, *, model: str | BaseChatModel | None = None, checkpointer=None):
    """A compiled agent. `rg` is the registration graph (Neo4jDeedGraph for the deed tool too); without it the agent has no registered-owner tool.
    `model` is a bare Claude model id (made `anthropic:<id>`), a provider:model string, or a chat model. Left out, it is AGENT_MODEL on
    AGENT_ANTHROPIC_API_KEY (evals pass their own model, built on the eval key)."""
    if model is None:
        model = agent_model()
    if isinstance(model, str) and ":" not in model:
        model = f"anthropic:{model}"
    # The lockdown is a harness profile registered for "anthropic" only. Another provider would silently get the default
    # file, shell and subagent tools back, so refuse it instead.
    if not (model.startswith("anthropic:") if isinstance(model, str) else isinstance(model, ChatAnthropic)):
        raise ValueError(f"Only Anthropic models are supported (the tool lockdown is registered for that provider): {model!r}")
    _lock_down()
    tools = [make_building_profile_tool(client, graph, pg)]
    if rg is not None:
        tools.append(make_registered_owner_tool(client, graph, rg))
        if hasattr(rg, "deeds"):          # the deed read lives on Neo4jDeedGraph; a registration-only graph gets no deed tool
            tools.append(make_deed_vs_owner_tool(client, graph, rg))
        if hasattr(rg, "contacts"):
            tools.append(make_building_contacts_tool(client, graph, rg))
        if hasattr(rg, "timeline"):
            tools.append(make_deed_timeline_tool(client, graph, rg))
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt(),
        permissions=[FilesystemPermission(operations=["read", "write"], paths=["/**"], mode="deny")],
        middleware=[RepeatGuardMiddleware()],
        response_format=ToolStrategy(ModelAnswer),     # the model's final message is a ModelAnswer; chat.ask assembles the rest
        checkpointer=checkpointer,
        name="watchline",
    )
