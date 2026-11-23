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
from watchline.agent.answer import Answer, ModelAnswer, assemble, render_markdown, ungrounded_numbers


@dataclass
class Turn:
    answer: str                                               # the markdown rendering of `structured`, or the model's last text
    tool_calls: list[dict] = field(default_factory=list)      # [{"name", "args"}] in order
    tool_results: list[dict] = field(default_factory=list)    # parsed tool outputs, in order
    structured: Answer | None = None                          # None only if the stream ended without one (a malformed one raises)
    corrected: list[str] = field(default_factory=list)        # numbers the first attempt made up and the model was asked to redo
    unverified: list[str] = field(default_factory=list)       # numbers in the final text that the records do not contain
    result_ids: set = field(default_factory=set, repr=False)  # message ids of the tool results this turn used

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


CORRECTION_PREFIX = "[correction]"
CORRECTION = (CORRECTION_PREFIX + " Your last answer contains numbers that are not in the tool results: {numbers}. Do not count or "
              "add anything yourself. Answer again, with every number copied from the tool results exactly as given.")


def thread_context(agent, config: dict) -> tuple[list[tuple[str | None, dict]], list[str]]:
    """Every tool result (with its message id) and every user message in the thread so far, corrections excluded, so a follow-up can
    cite an earlier lookup and a number the user typed counts as given. Empty if the agent has no checkpointer."""
    try:
        messages = agent.get_state(config).values.get("messages", [])
    except Exception:    # noqa: BLE001  no checkpointer, or a stand-in agent: there is no history to read
        return [], []
    results, users = [], []
    for m in messages:
        kind, content = getattr(m, "type", None), getattr(m, "content", None)
        if kind == "tool" and isinstance(content, str) and getattr(m, "name", None) != ModelAnswer.__name__:
            try:
                results.append((getattr(m, "id", None), json.loads(content)))
            except ValueError:
                pass
        elif kind == "human" and isinstance(content, str) and not content.startswith(CORRECTION_PREFIX):
            users.append(content)
    return results, users


def _run(agent, text: str, config: dict, on_tool_call=None, carry: list[dict] = (), carry_ids: set = frozenset()) -> Turn:
    """One message on the thread. `carry` are tool results from the attempt this one corrects: they count as this turn's."""
    turn = Turn(answer="")
    final = None
    ids: set = set(carry_ids)
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
                    ids.add(getattr(m, "id", None))
                    try:
                        turn.tool_results.append(json.loads(m.content) if isinstance(m.content, str) else m.content)
                    except ValueError:
                        turn.tool_results.append({"raw": str(m.content)[:200]})
    turn.result_ids = ids
    if final is not None:
        earlier = [r for i, r in thread_context(agent, config)[0] if i not in ids]
        turn.structured = assemble(final, [*carry, *turn.tool_results], earlier)
        turn.answer = render_markdown(turn.structured)
    return turn


def _grounding(turn: Turn) -> list[dict]:
    """The tool data a turn's answer may use: this turn's results plus the data its facts cite (which may be from earlier turns)."""
    cited = [e.data for f in turn.structured.facts for e in f.evidence] if turn.structured else []
    sources = {"sources": turn.structured.sources} if turn.structured else {}
    return [*turn.tool_results, *cited, sources]


def ask(agent, text: str, config: dict, on_tool_call=None) -> Turn:
    """Send one user message on a thread and return the final answer plus the tools called.

    If the model's text holds a number that appears nowhere in the tool data it used or in the user's messages (a count it added up
    or made up), it is asked once to answer again; `Turn.corrected` lists those numbers. If the second answer still has such numbers
    they are listed in `Turn.unverified` and the chat says so.
    """
    turn = _run(agent, text, config, on_tool_call)
    if turn.structured is None:
        return turn
    users = thread_context(agent, config)[1]
    stray = ungrounded_numbers(turn.model_text, _grounding(turn), " ".join(users) or text)
    if not stray:
        return turn
    if not users:                       # no thread history (no checkpointer): a correction message could not see the answer
        turn.unverified = stray
        return turn
    try:
        retry = _run(agent, CORRECTION.format(numbers=", ".join(stray)), config, on_tool_call, carry=turn.tool_results,
                     carry_ids=turn.result_ids)
    except Exception:    # noqa: BLE001  the first answer is still a complete answer; do not lose it to a failed second try
        turn.unverified = stray
        return turn
    if retry.structured is None:
        turn.unverified = stray
        return turn
    retry.tool_calls = [*turn.tool_calls, *retry.tool_calls]
    retry.tool_results = [*turn.tool_results, *retry.tool_results]
    retry.corrected = stray
    retry.unverified = ungrounded_numbers(retry.model_text, _grounding(retry), " ".join(users) or text)
    return retry


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
        notes = []
        if turn.structured is None:
            notes.append("The model did not return a structured answer, so no caveats or sources are attached to this reply.")
        if turn.unverified:
            notes.append(f"These numbers are not in the records and should not be trusted: {', '.join(turn.unverified)}.")
        write(f"\n{turn.answer}\n" + "".join(f"\n[{n}]\n" for n in notes))


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
