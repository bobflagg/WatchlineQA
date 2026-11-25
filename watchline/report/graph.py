"""The report graphs (design: docs/plans/identity-checkpoint.md and docs/plans/report-graph-build.md).

`build_identity_graph` is the identity checkpoint alone: one LangGraph workflow with one human pause. `build_report_graph` is the whole PESP report for a building
address: resolve, the sections in order, the identity checkpoint with its pause, and the assembled report. Both use the same pause logic and call no model.

The identity checkpoint, first.

No model is called. The nodes are the deterministic functions of `watchline.identity`; the only thing LangGraph adds is the pause. The graph
proposes the links for a landlord name, stops at `interrupt()` with the leads awaiting a decision, and, once resumed with the researcher's
decisions, finishes. The decisions are the only input that comes from outside, and they are saved in the result as a JSON log, so the same
log on the same graph snapshot reproduces the report without the graph runner (`identity_checkpoint(ig, name, decisions)`).

Rules of `interrupt()` kept here: the node that pauses has no side effects before the pause (it re-runs from the top on resume), it pauses once
per run, and a bad answer is sent back to the same node through the state, not through a loop inside the node. The researcher's `decidedAt`
comes from the caller, never from the clock, so a run is reproducible.
"""
import json
from dataclasses import asdict, dataclass
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from watchline.agent import tools as T
from watchline.agent.answer import Answer, CaveatOut
from watchline.conditions.conditions import build_litigation, build_violations
from watchline.contacts.contacts import build_contacts
from watchline.deeds.deeds import build_comparison
from watchline.deeds.timeline import build_timeline
from watchline.geosupport.resolution import Answer as Resolution
from watchline.geosupport.resolution import BoroughRequired, Match, resolve_text
from watchline.identity.checkpoint import DECISIONS, Decision
from watchline.identity.graph import IdentityGraph
from watchline.identity.section import (
    checkpoint_to_dict,
    decisions_from_json,
    decisions_to_json,
    identity_checkpoint,
    to_answer,
)
from watchline.profile.profile import build_profile
from watchline.registration.registration import build_registrations
from watchline.report import sections as S

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


def check_decisions(answer: Any, proposal: dict) -> None:
    """Raise ValueError (with the reason, for the pause to show) unless `answer` is {"decisions": [...]} and every decision is accept or reject, on a link of
    the proposal, and not an accept of a link that has only set-aside evidence."""
    if not isinstance(answer, dict) or not isinstance(answer.get("decisions"), list):
        raise ValueError('answer with {"decisions": [...]}; an empty list leaves every link awaiting')
    new = _decisions(answer["decisions"])               # validate the shape; the objects are built again at the end
    states = {x["linkId"]: x["state"] for x in proposal["links"]}
    for d in new:
        if d.decision not in DECISIONS:
            raise ValueError(f"decision {d.decision!r} on {d.linkId!r} must be accept or reject")
        if d.linkId not in states:
            raise ValueError(f"no link has the id {d.linkId!r}; the links are {sorted(states)}")
        if d.decision == "accept" and states[d.linkId] == "unsupported":
            raise ValueError(f"{d.linkId!r} has only set-aside evidence, so it cannot be accepted")


GRAPH_CHANGED = {"code": "graph_changed_since_proposal", "text": (
    "The graph changed between the proposal and the resume: the links now differ from the ones the decisions were made against. "
    "Check the links and decisions again.")}


def decision_prompt(state: dict) -> dict:
    p = state["proposal"]
    return {"kind": PROMPT, "name": state["name"], "error": state.get("error"),
            "links": [x for x in p["links"] if x["state"] == "awaiting"],
            "portfolio_effect": p["portfolio_effect"], "caveats": p["caveats"],
            "expects": {"decisions": [{"linkId": "…", "decision": "accept | reject", "decidedBy": "a role", "decidedAt": "…", "note": "optional"}]}}


def build_identity_graph(ig: IdentityGraph, checkpointer: BaseCheckpointSaver | None = None):
    """Compile the identity checkpoint graph. `ig` is read-only; a checkpointer is required to pause and resume (the caller passes one, and a thread id per report)."""

    def propose(state: ReportState) -> dict:
        r = identity_checkpoint(ig, state["name"], [])
        return {"proposal": checkpoint_to_dict(r), "answer": to_answer(r).model_dump(), "decisions": [], "error": None}

    def needs_decision(state: ReportState) -> str:
        p = state["proposal"]
        return "decide" if p["status"] == "ok" and any(x["state"] == "awaiting" for x in p["links"]) else "finish"

    def decide(state: ReportState) -> dict:
        answer = interrupt(decision_prompt(state))                # nothing is read or written before this line
        try:
            check_decisions(answer, state["proposal"])
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
            answer["caveats"].append(GRAPH_CHANGED)
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


# ---- the whole report ---------------------------------------------------------------------------------------------------------

CHOOSE_LANDLORD = "choose_landlord"

# The report's sections in reading order, grouped under the PESP guide's five questions. `step` is the guide step the section answers.
SECTIONS = (
    ("building", "2", "About this building", "The building"),
    ("owner", "3", "Who is my landlord?", "Registered owner and contacts"),
    ("entity", "5", "Who is my landlord?", "The owner entity"),
    ("identity", "6 and 7", "How many properties and where?", "Related landlord records and the portfolio"),
    ("deeds", "4", "Do they hold or sell?", "Deed history"),
    ("violations", "8", "What are the conditions?", "Violations"),
    ("litigation", "8", "What are the conditions?", "Housing Court cases"),
    ("web", "9", "Is there news?", "Web research"),
)


@dataclass(frozen=True)
class ReportDeps:
    """What the report reads: all of it read-only. `rg` serves registrations, deeds, the timeline, contacts and conditions (`Neo4jTimelineGraph`)."""
    client: Any
    graph: Any          # the Geosupport side of address resolution (`Neo4jGraph`)
    pg: Any             # the profile graph
    rg: Any
    ig: Any             # the identity graph


def _merge(a: dict, b: dict) -> dict:
    return {**(a or {}), **b}


class FullState(ReportState, total=False):
    text: str                      # the address as typed
    borough: str | None
    zip5: str | None
    generated_at: str              # supplied by the caller, never the clock, so a run is reproducible
    resolution: dict
    needs_input: dict | None       # the report stopped: the address needs a borough, a choice of street, or is not in the graph
    parts: Annotated[dict, _merge]   # section key -> Answer (JSON)
    landlord_names: list[str]
    checkpoint: dict | None        # the identity checkpoint after the decisions (JSON view), for the portfolio footprint
    report: dict


def resolution_to_state(r: Resolution) -> dict:
    return {**asdict(r), "outcome": str(r.outcome)}


def resolution_from_state(d: dict) -> Resolution:
    return Resolution(**{**d, "outcome": Match(d["outcome"]), "related_lots": tuple(d["related_lots"]), "candidates": tuple(d["candidates"]),
                         "tried": tuple(d["tried"])})


def _part(a: Answer) -> dict:
    return {"answer": a.model_dump()}


def build_report_graph(deps: ReportDeps, checkpointer: BaseCheckpointSaver | None = None):
    """Compile the PESP report graph for one building address. Input: {"text": the address, "borough": optional, "zip5": optional, "generated_at": a label}.

    It stops early (`needs_input`) when the address cannot be used. It pauses twice at most: to pick a landlord name when several records cover the lot, and for the
    researcher's decisions on the leads. Both pauses read nothing before they pause.
    """
    ig = deps.ig

    def resolve(state: FullState) -> dict:
        try:
            res = resolve_text(deps.client, deps.graph, state["text"], borough=state.get("borough"), zip5=state.get("zip5"))
        except BoroughRequired as e:
            return {"needs_input": {"status": "needs_borough", "message": f"{e}. Give the borough or a ZIP and run the report again."}}
        except ValueError as e:
            return {"needs_input": {"status": "invalid_input", "message": str(e)}}
        out: dict = {"resolution": resolution_to_state(res), "needs_input": None}
        if res.outcome is Match.AMBIGUOUS:
            out["needs_input"] = {"status": "ambiguous", "candidates": list(res.candidates),
                                  "message": "The street is ambiguous. Choose one of the candidate streets and run the report again; no lot was chosen."}
        elif res.outcome is Match.NOT_FOUND:
            out["needs_input"] = {"status": "not_found", "message": f"No lot was found (Geosupport return code {res.grc}). Spellings tried: {', '.join(res.tried) or 'none'}."}
        elif res.outcome is Match.UNAVAILABLE:
            out["needs_input"] = {"status": "error", "message": "Geosupport could not be reached. This is an outage, not an answer about the address."}
        elif not res.in_graph:
            out["needs_input"] = {"status": "not_in_graph", "message": f"Geosupport returned lot {res.bbl}, but the graph holds no such lot, so nothing could be read for it."}
        return out

    def after_resolve(state: FullState) -> str:
        return "assemble" if state.get("needs_input") else "building_facts"

    def res(state: FullState) -> Resolution:
        return resolution_from_state(state["resolution"])

    def building_facts(state: FullState) -> dict:
        return {"parts": {"building": _part(S.building_facts(T.profile_to_dict(build_profile(res(state), deps.pg))))}}

    def owner_and_contacts(state: FullState) -> dict:
        r = res(state)
        reg, con = T.registrations_to_dict(build_registrations(r, deps.rg)), T.contacts_to_dict(build_contacts(r, deps.rg))
        return {"parts": {"owner": _part(S.owner_and_contacts(reg, con))}}

    def deed_history(state: FullState) -> dict:
        r = res(state)
        tl, cmp = T.timeline_to_dict(build_timeline(r, deps.rg)), T.deeds_to_dict(build_comparison(r, deps.rg, deps.rg))
        return {"parts": {"deeds": _part(S.deed_history(tl, cmp))}}

    def entity_research(state: FullState) -> dict:
        return {"parts": {"entity": _part(S.not_covered("Entity research", "The New York State record for the owner entity (its type, filing date, registered agent and "
                                                                           "process address) is not in this report yet. The graph holds New York entities only where they match "
                                                                           "an owner name, and an out-of-state parent needs a web search by the researcher."))}}

    def landlords(state: FullState) -> dict:
        names = ig.landlords_covering(res(state).bbl)
        return {"landlord_names": names, **({"name": names[0]} if len(names) == 1 else {})}

    def after_landlords(state: FullState) -> str:
        n = len(state["landlord_names"])
        return "no_landlord" if n == 0 else "propose" if n == 1 else "choose_landlord"

    def no_landlord(state: FullState) -> dict:
        a = Answer(kind="not_found", summary=("No landlord record in the graph covers this lot, so there is no owner portfolio to show for it. That is not a statement "
                                              "that the owner holds no other buildings."),
                   caveats=[CaveatOut(code="no_landlord_record", text="The owner portfolio and operational network cover only lots that a landlord record covers.")])
        return {"parts": {"identity": _part(a)}, "checkpoint": None}

    def choose_landlord(state: FullState) -> dict:
        answer = interrupt({"kind": CHOOSE_LANDLORD, "names": state["landlord_names"], "error": state.get("error"),
                            "expects": {"name": "one of the names"}})      # nothing is read or written before this line
        if not isinstance(answer, dict) or answer.get("name") not in state["landlord_names"]:
            return {"error": f"answer with {{\"name\": one of {state['landlord_names']}}}"}
        return {"name": answer["name"], "error": None}

    def after_choose(state: FullState) -> str:
        return "choose_landlord" if state.get("error") else "propose"

    def propose(state: FullState) -> dict:
        r = identity_checkpoint(ig, state["name"], [])
        return {"proposal": checkpoint_to_dict(r), "parts": {"identity": _part(to_answer(r))}, "decisions": [], "error": None}

    def needs_decision(state: FullState) -> str:
        p = state["proposal"]
        return "decide" if p["status"] == "ok" and any(x["state"] == "awaiting" for x in p["links"]) else "finish_identity"

    def decide(state: FullState) -> dict:
        answer = interrupt(decision_prompt(state))                # nothing is read or written before this line
        try:
            check_decisions(answer, state["proposal"])
        except (ValueError, TypeError) as e:
            return {"error": str(e)}
        return {"decisions": [*state.get("decisions", []), *answer["decisions"]], "error": None}

    def after_decide(state: FullState) -> str:
        return "decide" if state.get("error") else "finish_identity"

    def finish_identity(state: FullState) -> dict:
        decisions = _decisions(state.get("decisions", []))
        r = identity_checkpoint(ig, state["name"], decisions)
        answer = to_answer(r).model_dump()
        before = {x["linkId"] for x in state["proposal"].get("links", [])}
        now = {x.linkId for x in r.checkpoint.links} if r.checkpoint else set()
        if before != now:
            answer["caveats"].append(GRAPH_CHANGED)
        return {"parts": {"identity": {"answer": answer}}, "checkpoint": checkpoint_to_dict(r), "decision_log": decisions_to_json(decisions)}

    def conditions(state: FullState) -> dict:
        r = res(state)
        return {"parts": {"violations": _part(S.violations_section(T.violations_to_dict(build_violations(r, deps.rg)))),
                          "litigation": _part(S.litigation_section(T.litigation_to_dict(build_litigation(r, deps.rg))))}}

    def web_research(state: FullState) -> dict:
        return {"parts": {"web": _part(S.not_covered("Web research", "Searching the news and the web for the owner names and addresses is a step for the researcher; "
                                                                      "web results are context, never identity evidence, and none are in this report."))}}

    def assemble(state: FullState) -> dict:
        parts = state.get("parts") or {}
        sections = [{"key": k, "step": step, "question": question, "title": title, "answer": parts[k]["answer"]}
                    for k, step, question, title in SECTIONS if k in parts]
        r = state.get("resolution") or {}
        sources = list(dict.fromkeys(src for sec in sections for src in sec["answer"]["sources"]))
        report = {"status": "needs_input" if state.get("needs_input") else "ok", "needs_input": state.get("needs_input"), "address": r.get("returned") or state["text"],
                  "typed": state["text"], "bbl": r.get("bbl"), "generated_at": state.get("generated_at"), "landlord": state.get("name"), "sections": sections,
                  "sources": sources, "decisions": state.get("decisions", []), "decision_log": state.get("decision_log", "[]"), "checkpoint": state.get("checkpoint")}
        return {"report": report}

    g = StateGraph(FullState)
    for name, fn in (("resolve", resolve), ("building_facts", building_facts), ("owner_and_contacts", owner_and_contacts), ("deed_history", deed_history),
                     ("entity_research", entity_research), ("landlords", landlords), ("no_landlord", no_landlord), ("choose_landlord", choose_landlord),
                     ("propose", propose), ("decide", decide), ("finish_identity", finish_identity), ("conditions", conditions),
                     ("web_research", web_research), ("assemble", assemble)):
        g.add_node(name, fn)
    g.add_edge(START, "resolve")
    g.add_conditional_edges("resolve", after_resolve, {"assemble": "assemble", "building_facts": "building_facts"})
    g.add_edge("building_facts", "owner_and_contacts")
    g.add_edge("owner_and_contacts", "deed_history")
    g.add_edge("deed_history", "entity_research")
    g.add_edge("entity_research", "landlords")
    g.add_conditional_edges("landlords", after_landlords, {"no_landlord": "no_landlord", "propose": "propose", "choose_landlord": "choose_landlord"})
    g.add_conditional_edges("choose_landlord", after_choose, {"choose_landlord": "choose_landlord", "propose": "propose"})
    g.add_conditional_edges("propose", needs_decision, {"decide": "decide", "finish_identity": "finish_identity"})
    g.add_conditional_edges("decide", after_decide, {"decide": "decide", "finish_identity": "finish_identity"})
    g.add_edge("no_landlord", "conditions")
    g.add_edge("finish_identity", "conditions")
    g.add_edge("conditions", "web_research")
    g.add_edge("web_research", "assemble")
    g.add_edge("assemble", END)
    return g.compile(checkpointer=checkpointer)
