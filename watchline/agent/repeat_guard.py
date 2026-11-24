"""Stop a model from looking up the same thing over and over within one user message.

Seen live (docs/plans/eval-cost.md, Stage 3): after a correct `building_profile` result the model emitted the identical call again, with
no text, until a limit stopped it. This middleware answers the second identical call in a turn with a short fixed message instead of
running the tool, which tells the model it already has the data and should write its answer. The first call always runs.

A turn is everything after the latest human message (a "[correction]" message is a human message, so a correction may look up again).
"""
import json

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

NUDGE = {"status": "repeat_lookup",
         "message": "You already looked this up in this turn and have its result above. Do not call the tool again with the same "
                    "arguments. Write your structured answer now, from that result."}


def _key(name: str, args: dict) -> str:
    return name + json.dumps(args, sort_keys=True, default=str)


class RepeatGuardMiddleware(AgentMiddleware):
    """Replaces a repeated identical tool call, within one turn, with NUDGE. `blocked` lists what was replaced (for the usage log)."""

    def __init__(self) -> None:
        super().__init__()
        self.blocked: list[dict] = []

    def wrap_tool_call(self, request, handler):
        call = request.tool_call
        messages = request.state.get("messages", []) if isinstance(request.state, dict) else []
        start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        answered = {m.tool_call_id for m in messages[start + 1:] if isinstance(m, ToolMessage)}
        wanted = _key(call["name"], call["args"])
        for m in messages[start + 1:]:
            if isinstance(m, AIMessage):
                for earlier in m.tool_calls:
                    if earlier["id"] != call["id"] and earlier["id"] in answered and _key(earlier["name"], earlier["args"]) == wanted:
                        self.blocked.append({"name": call["name"], "args": call["args"]})
                        return ToolMessage(content=json.dumps(NUDGE), tool_call_id=call["id"], name=call["name"])
        return handler(request)
