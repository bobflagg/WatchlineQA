"""Terminal chat: `make chat`. One conversation per run (in-memory thread); each tool call is shown as it happens.

Credentials come from .env through python-dotenv and are never printed.
"""
import json
import os
import sys
import uuid
from dataclasses import dataclass, field

from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage

from watchline.agent.agent import build_agent


@dataclass
class Turn:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)      # [{"name", "args"}] in order
    tool_results: list[dict] = field(default_factory=list)    # parsed tool outputs, in order


def text_of(message) -> str:
    """The text of a model message; Anthropic returns a list of content blocks."""
    c = message.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def ask(agent, text: str, config: dict, on_tool_call=None) -> Turn:
    """Send one user message on a thread and return the final answer plus the tools called."""
    turn = Turn(answer="")
    for chunk in agent.stream({"messages": [{"role": "user", "content": text}]}, config, stream_mode="updates"):
        for update in chunk.values():
            for m in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                if isinstance(m, AIMessage):
                    for call in m.tool_calls:
                        turn.tool_calls.append({"name": call["name"], "args": call["args"]})
                        if on_tool_call:
                            on_tool_call(call["name"], call["args"])
                    if not m.tool_calls and text_of(m).strip():
                        turn.answer = text_of(m)
                elif getattr(m, "type", None) == "tool":
                    try:
                        turn.tool_results.append(json.loads(m.content) if isinstance(m.content, str) else m.content)
                    except ValueError:
                        turn.tool_results.append({"raw": str(m.content)[:200]})
    return turn


def connect():
    """Real clients from the environment. Returns (client, graph, profile_graph, close)."""
    from neo4j import GraphDatabase

    from watchline.geosupport.geosupport import Client
    from watchline.geosupport.resolution import Neo4jGraph
    from watchline.profile.profile import Neo4jProfileGraph

    load_dotenv(find_dotenv(usecwd=True))
    db = os.environ["NEO4J_DATABASE"]
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    return Client(), Neo4jGraph(driver, db), Neo4jProfileGraph(driver, db), driver.close


def main() -> int:
    from langgraph.checkpoint.memory import InMemorySaver

    load_dotenv(find_dotenv(usecwd=True))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (put it in .env).", file=sys.stderr)
        return 2
    client, graph, pg, close = connect()
    agent = build_agent(client, graph, pg, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("Watchline. Ask about a New York City address (for example: 224 54 Street, Brooklyn). Ctrl-D to quit.\n")
    try:
        while True:
            try:
                text = input("you> ").strip()
            except EOFError:
                print()
                break
            if not text:
                continue
            turn = ask(agent, text, config, on_tool_call=lambda n, a: print(f"  -> {n}({json.dumps(a)})"))
            print(f"\n{turn.answer}\n")
    finally:
        close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
