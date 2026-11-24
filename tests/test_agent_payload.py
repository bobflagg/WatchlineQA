"""What the agent really sends the model on each call (system text and tool schemas), measured with a scripted model.

This settles how many tokens Deep Agents adds on top of our own prompt and tools. Run `uv run pytest tests/test_agent_payload.py -s`
to print the sizes. The bounds are loose on purpose: they catch a Deep Agents upgrade that starts injecting prose or tools.
"""
import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from test_agent import final
from test_agent_tools import FakeClient, FakeGraph, _deed_rg, resolved
from test_profile import BUILDINGS, FakePG

from watchline.agent.agent import build_agent, memory_checkpointer, system_prompt
from watchline.agent.chat import ask


def captured_request():
    seen = {}

    class Spy(ChatAnthropic):
        def bind_tools(self, tools, **kw):
            seen["tools"] = [convert_to_openai_tool(t) for t in tools]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw):
            seen["messages"] = messages
            return ChatResult(generations=[ChatGeneration(message=final("hi"))])

    agent = build_agent(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS), _deed_rg(),
                        model=Spy(model="claude-haiku-5-5", api_key="dummy"), checkpointer=memory_checkpointer())
    ask(agent, "hi", {"configurable": {"thread_id": "t"}})
    return seen


def test_deep_agents_adds_no_prose_to_our_system_prompt_and_no_tools_beyond_ours():
    seen = captured_request()
    system = seen["messages"][0]
    text = "".join(b.get("text", "") for b in system.content if isinstance(b, dict)) if isinstance(system.content, list) else system.content
    ours = system_prompt()
    extra = len(text) - len(ours)
    tools = seen["tools"]
    tools_chars = len(json.dumps(tools))
    names = sorted(t["function"]["name"] for t in tools)
    print(f"\nsystem prompt: {len(text)} chars (ours {len(ours)}, added by Deep Agents {extra}); "
          f"tools {names}, schemas {tools_chars} chars; total about {(len(text) + tools_chars) // 4} tokens (4 chars per token)")
    assert names == ["ModelAnswer", "building_profile", "deed_vs_owner", "registered_owner"]
    assert text.startswith(ours[:200])
    assert extra < 200, f"Deep Agents now adds {extra} chars of prose to the system prompt: {text[len(ours):][:300]!r}"
    assert not isinstance(system, AIMessage)
