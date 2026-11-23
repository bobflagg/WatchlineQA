"""The real agent graph driven by a scripted model: no API key, no network. Checks the wiring, not the model's judgement."""
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import BUILDINGS, FakePG

from watchline.agent.agent import PROMPTS, build_agent, memory_checkpointer, system_prompt
from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact
from watchline.agent.chat import ask, converse, text_of


def tool_call(name, args, id_="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])


def final(summary="hello", kind="profile", facts=()):
    """The model's last message under the tool strategy: a call to the ModelAnswer tool."""
    args = ModelAnswer(kind=kind, summary=summary, facts=list(facts)).model_dump()
    return AIMessage(content="", tool_calls=[{"name": "ModelAnswer", "args": args, "id": "final-1"}])


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
                        checkpointer=memory_checkpointer(), **kw)
    return agent, seen


CONFIG = {"configurable": {"thread_id": "t1"}}


def test_model_is_offered_only_the_profile_tool():
    agent, seen = agent_with([final("hello")])
    ask(agent, "hi", CONFIG)
    assert seen["tools"] and all(t == ["ModelAnswer", "building_profile"] for t in seen["tools"])   # no file, shell or subagent tools


def test_system_prompt_carries_the_ontology_rules_from_the_single_source():
    prompt = system_prompt()
    assert "{ontology_rules}" not in prompt
    for line in (PROMPTS / "ontology_rules.md").read_text().strip().splitlines():
        assert line.strip() in prompt
    assert "building_profile" in prompt and "After Inquest" in prompt


def test_the_model_actually_receives_the_system_prompt():
    agent, seen = agent_with([final("hello")])
    ask(agent, "hi", CONFIG)
    system = seen["calls"][0][0]
    assert system.type == "system" and "Never merge identities" in str(system.content)


def test_tool_call_runs_the_real_tool_and_the_result_reaches_the_model():
    agent, seen = agent_with([tool_call("building_profile", {"address": "1 Main St", "borough": "Manhattan"}),
                              final("Lot 1000010001, two buildings.", facts=[
                                  ModelFact(statement="Resolved exactly.", evidence=[EvidenceRef(section="resolution")]),
                                  ModelFact(statement="Building 1 is the addressed one.", evidence=[EvidenceRef(section="buildings", bin="1")])])])
    turn = ask(agent, "tell me about 1 Main St, Manhattan", CONFIG, on_tool_call=lambda n, a: None)
    assert turn.tool_calls == [{"name": "building_profile", "args": {"address": "1 Main St", "borough": "Manhattan"}}]
    assert turn.tool_results[0]["status"] == "ok" and turn.tool_results[0]["resolution"]["bbl"] == "1000010001"
    assert turn.structured.summary == "Lot 1000010001, two buildings." and turn.answer.startswith("Lot 1000010001")
    assert [f.unresolved for f in turn.structured.facts] == [[], []]
    assert {c.code for c in turn.structured.caveats} >= {"cited_not_fault", "lot_wide"} and turn.structured.sources
    second_call = seen["calls"][1]
    assert any("1000010001" in str(m.content) for m in second_call if m.type == "tool")


def test_needs_borough_flows_back_to_the_model_as_data():
    agent, seen = agent_with([tool_call("building_profile", {"address": "1 Main St"}), final("Which borough?", kind="clarification")])
    turn = ask(agent, "1 Main St", CONFIG)
    assert turn.tool_results[0]["status"] == "needs_borough"
    assert turn.answer == "Which borough?" and turn.structured.kind == "clarification" and turn.structured.caveats == []


def test_a_call_to_a_removed_builtin_tool_does_not_run():
    agent, seen = agent_with([tool_call("write_file", {"file_path": "/x.txt", "content": "hi"}), final("done", kind="refusal")])
    turn = ask(agent, "write a file", CONFIG)
    assert turn.answer == "done"
    tool_msgs = [m for m in seen["calls"][1] if m.type == "tool"]
    assert tool_msgs and str(tool_msgs[-1].content).startswith("Error") and "not available" in str(tool_msgs[-1].content)


def test_follow_up_turn_keeps_the_thread():
    agent, seen = agent_with([final("first"), final("second")])
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


@pytest.mark.parametrize("model", ["openai:gpt-5", "google_genai:gemini-3-pro"])
def test_a_non_anthropic_model_is_refused_because_the_lockdown_would_not_apply(model):
    with pytest.raises(ValueError, match="Only Anthropic"):
        build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), model=model)


def test_a_bare_model_id_means_anthropic():
    build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), model="claude-haiku-5-5")   # no error, no network


class Boom:
    """An agent whose stream fails, like an API outage."""
    def stream(self, *a, **kw):
        raise RuntimeError("secret-looking detail that must not be printed")


def run_chat(agent, lines):
    out, it = [], iter(lines)

    def read(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    converse(agent, CONFIG, read=read, write=lambda *a: out.append(" ".join(map(str, a))))
    return out


def test_chat_survives_a_failed_turn_and_does_not_print_the_error_text(capsys):
    run_chat(Boom(), ["first", "second"])
    err = capsys.readouterr().err
    assert err.count("RuntimeError") == 2 and "secret-looking" not in err


def test_chat_answers_then_exits_on_eof():
    agent, _ = agent_with([final("hello there")])
    out = run_chat(agent, ["hi", "", "  "])
    assert any("hello there" in line for line in out)


def test_caveats_and_sources_come_from_the_tool_not_from_what_the_model_wrote():
    agent, _ = agent_with([tool_call("building_profile", {"address": "1 Main St", "borough": "Manhattan"}),
                           final("All clear. No caveats apply and none are needed.")])
    turn = ask(agent, "tell me about 1 Main St, Manhattan", CONFIG)
    assert "cited_not_fault" in turn.structured.caveat_codes and "not findings of fault" in turn.answer
    assert "not findings of fault" not in turn.model_text


def test_a_final_message_that_is_not_the_structure_gives_no_structured_answer_and_chat_says_so(capsys):
    agent, _ = agent_with([AIMessage(content="just some prose")])
    turn = ask(agent, "hi", CONFIG)
    assert turn.structured is None and turn.answer == "just some prose" and turn.model_text == "just some prose"
    agent, _ = agent_with([AIMessage(content="just some prose")])
    out = run_chat(agent, ["hi"])
    assert any("just some prose" in line for line in out) and "no caveats or sources are attached" in capsys.readouterr().err


def test_a_follow_up_with_no_new_lookup_cites_the_earlier_turns_result():
    agent, _ = agent_with([tool_call("building_profile", {"address": "1 Main St", "borough": "Manhattan"}), final("Two buildings."),
                           final("Building 2 is 3 Main St.", facts=[ModelFact(statement="BIN 2 is at 3 MAIN ST.",
                                                                             evidence=[EvidenceRef(section="buildings", bin="2")])])])
    ask(agent, "tell me about 1 Main St, Manhattan", CONFIG)
    turn = ask(agent, "and the other building?", CONFIG)
    assert turn.tool_calls == [] and turn.structured.facts[0].unresolved == []
    assert turn.structured.facts[0].evidence[0].data["bin"] == "2" and "cited_not_fault" in turn.structured.caveat_codes
