"""The real agent graph driven by a scripted model: no API key, no network. Checks the wiring, not the model's judgement."""
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import BUILDINGS, FakePG

from watchline.agent.agent import PROMPTS, build_agent, system_prompt
from watchline.agent.chat import ask, text_of


def tool_call(name, args, id_="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])


def scripted(responses):
    """A ChatAnthropic that answers from a script and records what the agent offers it."""
    seen = {"tools": [], "calls": []}
    it = iter(responses)

    class Scripted(ChatAnthropic):
        def bind_tools(self, tools, **kw):
            seen["tools"].append(sorted(getattr(t, "name", None) or t.get("name") for t in tools))
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw):
            seen["calls"].append(messages)
            return ChatResult(generations=[ChatGeneration(message=next(it))])

    return Scripted(model="claude-haiku-5-5", api_key="dummy"), seen


def agent_with(responses, **kw):
    model, seen = scripted(responses)
    agent = build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), model=model,
                        checkpointer=InMemorySaver(), **kw)
    return agent, seen


CONFIG = {"configurable": {"thread_id": "t1"}}


def test_model_is_offered_only_the_profile_tool():
    agent, seen = agent_with([AIMessage(content="hello")])
    ask(agent, "hi", CONFIG)
    assert seen["tools"] and all(t == ["building_profile"] for t in seen["tools"])   # no file, shell or subagent tools


def test_system_prompt_carries_the_ontology_rules_from_the_single_source():
    prompt = system_prompt()
    assert "{ontology_rules}" not in prompt
    for line in (PROMPTS / "ontology_rules.md").read_text().strip().splitlines():
        assert line.strip() in prompt
    assert "building_profile" in prompt and "After Inquest" in prompt


def test_the_model_actually_receives_the_system_prompt():
    agent, seen = agent_with([AIMessage(content="hello")])
    ask(agent, "hi", CONFIG)
    system = seen["calls"][0][0]
    assert system.type == "system" and "Never merge identities" in str(system.content)


def test_tool_call_runs_the_real_tool_and_the_result_reaches_the_model():
    agent, seen = agent_with([tool_call("building_profile", {"address": "1 Main St", "borough": "Manhattan"}),
                              AIMessage(content=[{"type": "text", "text": "Lot 1000010001, two buildings."}])])
    turn = ask(agent, "tell me about 1 Main St, Manhattan", CONFIG, on_tool_call=lambda n, a: None)
    assert turn.tool_calls == [{"name": "building_profile", "args": {"address": "1 Main St", "borough": "Manhattan"}}]
    assert turn.tool_results[0]["status"] == "ok" and turn.tool_results[0]["resolution"]["bbl"] == "1000010001"
    assert turn.answer == "Lot 1000010001, two buildings."
    second_call = seen["calls"][1]
    assert any("1000010001" in str(m.content) for m in second_call if m.type == "tool")


def test_needs_borough_flows_back_to_the_model_as_data():
    agent, seen = agent_with([tool_call("building_profile", {"address": "1 Main St"}), AIMessage(content="Which borough?")])
    turn = ask(agent, "1 Main St", CONFIG)
    assert turn.tool_results[0]["status"] == "needs_borough"
    assert turn.answer == "Which borough?"


def test_a_call_to_a_removed_builtin_tool_does_not_run():
    agent, seen = agent_with([tool_call("write_file", {"file_path": "/x.txt", "content": "hi"}), AIMessage(content="done")])
    turn = ask(agent, "write a file", CONFIG)
    assert turn.answer == "done"
    tool_msgs = [m for m in seen["calls"][1] if m.type == "tool"]
    assert tool_msgs and "Updated" not in str(tool_msgs[-1].content) and "Wrote" not in str(tool_msgs[-1].content)


def test_follow_up_turn_keeps_the_thread():
    agent, seen = agent_with([AIMessage(content="first"), AIMessage(content="second")])
    ask(agent, "my first question", CONFIG)
    turn = ask(agent, "and a follow-up", CONFIG)
    assert turn.answer == "second"
    history = " ".join(str(m.content) for m in seen["calls"][1])
    assert "my first question" in history and "first" in history


def test_text_of_handles_string_and_content_blocks():
    assert text_of(AIMessage(content="plain")) == "plain"
    blocks = [{"type": "text", "text": "a"}, {"type": "tool_use", "id": "x", "name": "n", "input": {}}, {"type": "text", "text": "b"}]
    assert text_of(AIMessage(content=blocks)) == "ab"


@pytest.mark.parametrize("name", ["system.md", "ontology_rules.md"])
def test_prompt_files_exist_and_are_not_empty(name):
    assert (PROMPTS / name).read_text().strip()
