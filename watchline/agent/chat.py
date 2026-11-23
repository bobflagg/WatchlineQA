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

from watchline.agent.agent import build_agent, memory_checkpointer
from watchline.agent.answer import Answer, ModelAnswer, assemble, render_markdown


@dataclass
class Turn:
    answer: str                                               # the markdown rendering of `structured`, or the model's last text
    tool_calls: list[dict] = field(default_factory=list)      # [{"name", "args"}] in order
    tool_results: list[dict] = field(default_factory=list)    # parsed tool outputs, in order
    structured: Answer | None = None                          # None only if the stream ended without one (a malformed one raises)

    @property
    def model_text(self) -> str:
        """What the model itself wrote (summary and fact statements), without the attached caveats and sources."""
        return self.structured.model_text if self.structured else self.answer


def text_of(message) -> str:
    """The text of a model message; Anthropic returns a list of content blocks."""
    c = message.content
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def earlier_results(agent, config: dict, this_turn: int) -> list[dict]:
    """Tool results from earlier turns of the thread, so a follow-up can cite what an earlier lookup returned."""
    try:
        messages = agent.get_state(config).values.get("messages", [])
    except Exception:    # noqa: BLE001  no checkpointer, or a stand-in agent: there is no history to read
        return []
    out = []
    for m in messages:
        if getattr(m, "type", None) == "tool" and isinstance(m.content, str):
            try:
                out.append(json.loads(m.content))
            except ValueError:
                pass
    return out[:len(out) - this_turn] if this_turn else out


def ask(agent, text: str, config: dict, on_tool_call=None) -> Turn:
    """Send one user message on a thread and return the final answer plus the tools called."""
    turn = Turn(answer="")
    final = None
    for chunk in agent.stream({"messages": [{"role": "user", "content": text}]}, config, stream_mode="updates"):
        for update in chunk.values():
            if isinstance(update, dict) and update.get("structured_response") is not None:
                final = update["structured_response"]
            for m in (update or {}).get("messages", []) if isinstance(update, dict) else []:
                if isinstance(m, AIMessage):
                    for call in m.tool_calls:
                        if call["name"] == ModelAnswer.__name__:      # the answer schema as a tool (tool strategy), not a tool call
                            continue
                        turn.tool_calls.append({"name": call["name"], "args": call["args"]})
                        if on_tool_call:
                            on_tool_call(call["name"], call["args"])
                    if not m.tool_calls and text_of(m).strip():
                        turn.answer = text_of(m)
                elif getattr(m, "type", None) == "tool" and getattr(m, "name", None) != ModelAnswer.__name__:
                    try:
                        turn.tool_results.append(json.loads(m.content) if isinstance(m.content, str) else m.content)
                    except ValueError:
                        turn.tool_results.append({"raw": str(m.content)[:200]})
    if final is not None:
        turn.structured = assemble(final, turn.tool_results, earlier_results(agent, config, len(turn.tool_results)))
        turn.answer = render_markdown(turn.structured)
    return turn


class StartupError(Exception):
    """Something the environment must provide is missing or unreachable. The message is safe to print."""


def connect():
    """Real clients from the environment. Returns (client, graph, profile_graph, close). Raises StartupError."""
    import httpx
    from neo4j import GraphDatabase

    from watchline.geosupport.geosupport import Client
    from watchline.geosupport.resolution import Neo4jGraph
    from watchline.profile.profile import Neo4jProfileGraph

    load_dotenv(find_dotenv(usecwd=True))
    missing = [k for k in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE") if not os.environ.get(k)]
    if missing:
        raise StartupError(f"{', '.join(missing)} not set (put them in .env).")
    db = os.environ["NEO4J_DATABASE"]
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        raise StartupError(f"Neo4j is not reachable or refused the credentials ({type(exc).__name__}).") from None
    client = Client()
    try:
        client.health()
    except httpx.HTTPError:
        driver.close()
        raise StartupError(f"The Geosupport sidecar is not reachable at {client.url} (start it with `make sidecar`).") from None
    return client, Neo4jGraph(driver, db), Neo4jProfileGraph(driver, db), driver.close


def converse(agent, config: dict, read=input, write=print) -> None:
    """The chat loop. A failed turn is reported by its error type and the conversation goes on; EOF ends it."""
    while True:
        try:
            text = read("you> ").strip()
        except EOFError:
            write()
            return
        if not text:
            continue
        try:
            turn = ask(agent, text, config, on_tool_call=lambda n, a: write(f"  -> {n}({json.dumps(a)})"))
        except Exception as exc:    # an API or graph failure ends the turn, not the session; the error text is not shown
            print(f"\n[That question failed: {type(exc).__name__}. Nothing was answered; try again.]\n", file=sys.stderr)
            continue
        if turn.structured is None:
            print("\n[The model did not return a structured answer, so no caveats or sources are attached to this reply.]",
                  file=sys.stderr)
        write(f"\n{turn.answer}\n")


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set (put it in .env).", file=sys.stderr)
        return 2
    try:
        client, graph, pg, close = connect()
    except StartupError as exc:
        print(f"Cannot start: {exc}", file=sys.stderr)
        return 2
    agent = build_agent(client, graph, pg, checkpointer=memory_checkpointer())
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    print("Watchline. Ask about a New York City address (for example: 224 54 Street, Brooklyn). Ctrl-D to quit.\n")
    try:
        converse(agent, config)
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
