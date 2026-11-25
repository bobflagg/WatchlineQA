"""The report graph, first piece: the identity checkpoint as a LangGraph workflow with one human pause (design: docs/plans/identity-checkpoint.md).

No model is called. The nodes are the deterministic functions of `watchline.identity`; the only thing LangGraph adds is the pause. The graph
proposes the links for a landlord name, stops at `interrupt()` with the leads awaiting a decision, and, once resumed with the researcher's
decisions, finishes. The decisions are the only input that comes from outside, and they are saved in the result as a JSON log, so the same
log on the same graph snapshot reproduces the report without the graph runner (`identity_checkpoint(ig, name, decisions)`).

Rules of `interrupt()` kept here: the node that pauses has no side effects before the pause (it re-runs from the top on resume), it pauses once
per run, and a bad answer is sent back to the same node through the state, not through a loop inside the node. The researcher's `decidedAt`
comes from the caller, never from the clock, so a run is reproducible.
"""
import json
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from watchline.identity.checkpoint import DECISIONS, Decision
from watchline.identity.graph import IdentityGraph
from watchline.identity.section import (
    checkpoint_to_dict,
    decisions_from_json,
    decisions_to_json,
    identity_checkpoint,
    to_answer,
)

PROMPT = "identity_checkpoint_decision"


class ReportState(TypedDict, total=False):
    name: str                      # the landlord name as recorded
    proposal: dict                 # the checkpoint before any decision (JSON view)
    decisions: list[dict]          # the researcher's decisions so far, in the order given
    error: str | None              # why the last answer was not accepted; sent back to the same pause
    answer: dict                   # the Answer (JSON), with the decisions applied once the run has finished
    decision_log: str              # the decisions as the JSON text to save with the report


def _decisions(items: list[dict]) -> list[Decision]:
    return decisions_from_json(json.dumps(items))


def build_report_graph(ig: IdentityGraph, checkpointer: BaseCheckpointSaver | None = None):
    """Compile the graph. `ig` is read-only; a checkpointer is required to pause and resume (the caller passes one, and a thread id per report)."""

    def propose(state: ReportState) -> dict:
        r = identity_checkpoint(ig, state["name"], [])
        return {"proposal": checkpoint_to_dict(r), "answer": to_answer(r).model_dump(), "decisions": [], "error": None}

    def needs_decision(state: ReportState) -> str:
        p = state["proposal"]
        return "decide" if p["status"] == "ok" and any(x["state"] == "awaiting" for x in p["links"]) else "finish"

    def decide(state: ReportState) -> dict:
        p = state["proposal"]
        answer = interrupt({                                      # nothing is read or written before this line
            "kind": PROMPT, "name": state["name"], "error": state.get("error"),
            "links": [x for x in p["links"] if x["state"] == "awaiting"],
            "portfolio_effect": p["portfolio_effect"], "caveats": p["caveats"],
            "expects": {"decisions": [{"linkId": "…", "decision": "accept | reject", "decidedBy": "a role", "decidedAt": "…", "note": "optional"}]},
        })
        try:
            if not isinstance(answer, dict) or not isinstance(answer.get("decisions"), list):
                raise ValueError('answer with {"decisions": [...]}; an empty list leaves every link awaiting')
            new = _decisions(answer["decisions"])               # validate the shape; the objects are built again in `finish`
            states = {x["linkId"]: x["state"] for x in p["links"]}
            for d in new:
                if d.decision not in DECISIONS:
                    raise ValueError(f"decision {d.decision!r} on {d.linkId!r} must be accept or reject")
                if d.linkId not in states:
                    raise ValueError(f"no link has the id {d.linkId!r}; the links are {sorted(states)}")
                if d.decision == "accept" and states[d.linkId] == "unsupported":
                    raise ValueError(f"{d.linkId!r} has only set-aside evidence, so it cannot be accepted")
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        return {"decisions": [*state.get("decisions", []), *answer["decisions"]], "error": None}

    def after_decide(state: ReportState) -> str:
        return "decide" if state.get("error") else "finish"

    def finish(state: ReportState) -> dict:
        r = identity_checkpoint(ig, state["name"], _decisions(state.get("decisions", [])))
        answer = to_answer(r).model_dump()
        before = {x["linkId"] for x in state["proposal"].get("links", [])}
        now = {x.linkId for x in r.checkpoint.links} if r.checkpoint else set()
        if before != now:                                          # the graph changed between the pause and the resume
            answer["caveats"].append({"code": "graph_changed_since_proposal", "text": (
                "The graph changed between the proposal and the resume: the links now differ from the ones the decisions were made against. "
                "Check the links and decisions again.")})
        return {"answer": answer, "decision_log": decisions_to_json(_decisions(state.get("decisions", [])))}

    g = StateGraph(ReportState)
    g.add_node("propose", propose)
    g.add_node("decide", decide)
    g.add_node("finish", finish)
    g.add_edge(START, "propose")
    g.add_conditional_edges("propose", needs_decision, {"decide": "decide", "finish": "finish"})
    g.add_conditional_edges("decide", after_decide, {"decide": "decide", "finish": "finish"})
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)


def pending(result: dict) -> list[Any]:
    """The pause payloads in a result from `invoke`, or an empty list when the run finished."""
    return [i.value for i in result.get("__interrupt__", ())]
