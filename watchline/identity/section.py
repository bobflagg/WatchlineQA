"""The identity checkpoint as a section: the pure functions joined (graph reads, links, decisions, effect), a JSON view, and the Answer.

No model is involved. The Answer is built from templates, so the same snapshot and the same decisions give the same words, evidence and
caveats. The decisions come from a plain JSON file kept with the report (see `decisions_from_json`); the graph is never written.
"""
import json
from dataclasses import asdict, dataclass

from watchline.agent.answer import Answer, CaveatOut, Evidence, Fact
from watchline.identity.checkpoint import Checkpoint, Decision, Footprint, LinkOut, build_checkpoint
from watchline.identity.graph import SOURCE_HPD, SOURCE_NETWORK, IdentityGraph, Inputs, build_inputs
from watchline.profile.profile import PLUTO

SOURCES = (SOURCE_NETWORK, SOURCE_HPD, PLUTO)
DECISION_KEYS = {"linkId", "decision", "decidedBy", "decidedAt", "note"}


@dataclass(frozen=True)
class IdentityCheckpoint:
    inputs: Inputs
    checkpoint: Checkpoint | None = None


def identity_checkpoint(ig: IdentityGraph, name: str, decisions: list[Decision] | tuple[Decision, ...] = ()) -> IdentityCheckpoint:
    """Landlord name as recorded to the checkpoint. Reads the graph; applies the decisions; writes nothing."""
    inputs = build_inputs(ig, name)
    if inputs.status != "ok":
        return IdentityCheckpoint(inputs)
    return IdentityCheckpoint(inputs, build_checkpoint(inputs.anchor, inputs.links, decisions))


# ---- the decision file -------------------------------------------------------------------------------------------------

def decisions_from_json(text: str) -> list[Decision]:
    """The decision log saved with the report: a JSON list of objects with the keys of `Decision`. Raises ValueError on anything else."""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("the decision log must be a JSON list")
    out = []
    for i, d in enumerate(data):
        if not isinstance(d, dict) or not {"linkId", "decision", "decidedBy", "decidedAt"} <= d.keys() or not d.keys() <= DECISION_KEYS:
            raise ValueError(f"decision {i} must be an object with linkId, decision, decidedBy, decidedAt and optionally note")
        if not all(isinstance(d[k], str) for k in d if d[k] is not None):
            raise ValueError(f"decision {i} has a value that is not text")
        out.append(Decision(d["linkId"], d["decision"], d["decidedBy"], d["decidedAt"], d.get("note")))
    return out


def decisions_to_json(decisions: list[Decision] | tuple[Decision, ...]) -> str:
    return json.dumps([asdict(d) for d in decisions], indent=2, sort_keys=True)


# ---- the JSON view -----------------------------------------------------------------------------------------------------

def _link(x: LinkOut) -> dict:
    return {"linkId": x.linkId, "a": x.a, "b": x.b, "kind": x.kind, "basis": x.basis, "state": x.state, "rule": x.rule,
            "evidence": [asdict(e) for e in x.evidence], "against": list(x.against),
            "decision": None if x.decision is None else asdict(x.decision)}


def _footprint(f: Footprint) -> dict:
    return {"lots": f.lots, "units": f.units, "unitsMissing": f.unitsMissing, "parties": f.parties, "assumes": list(f.assumes)}


def checkpoint_to_dict(r: IdentityCheckpoint) -> dict:
    """JSON-safe view. `portfolio_effect` shows the portfolio as held and as decided side by side; nothing is summed into a score."""
    i, c = r.inputs, r.checkpoint
    out: dict = {"status": i.status, "name": i.name, "candidates": [list(x) for x in i.candidates],
                 "caveats": [x.as_dict() for x in (*i.caveats, *(c.caveats if c else ()))], "sources": list(SOURCES) if i.status == "ok" else []}
    if c is not None:
        out.update(anchor={"key": c.anchor, "records": i.anchor.records}, links=[_link(x) for x in c.links],
                   decisions=[asdict(d) for d in c.decisions], issues=[asdict(x) for x in c.issues],
                   portfolio_effect={"as_held": _footprint(c.effect.as_held), "as_decided": _footprint(c.effect.as_decided),
                                     "added_lots": list(c.effect.added_lots), "removed_lots": list(c.effect.removed_lots)})
    return out


# ---- the Answer, from templates ------------------------------------------------------------------------------------------

_KIND = {"address": "a shared business address", "name": "the network method's name comparison", "contact": "a shared contact",
         "identity": "an identity link"}


def _counts(f: dict) -> str:
    miss = f" (no unit count is recorded for {f['unitsMissing']} lot{'s' if f['unitsMissing'] != 1 else ''})" if f["unitsMissing"] else ""
    return f"{f['lots']} lots and {f['units']} residential units{miss}"


def _state(link: dict) -> str:
    d = link["decision"]
    who = f" (decided by {d['decidedBy']} on {d['decidedAt']}" + (f"; note: {d['note']}" if d.get("note") else "") + ")" if d else ""
    return {"awaiting": "A lead, awaiting the researcher's decision.",
            "accepted": f"Accepted by the researcher{who}. This is the researcher's inference, not a finding in the records.",
            "rejected": f"Rejected by the researcher{who}.",
            "accepted_by_method": "Already joined by the graph's identity method.",
            "unsupported": "All the shared evidence was set aside, so nothing supports this link."}[link["state"]]


def _link_statement(link: dict) -> str:
    how = _KIND[link["kind"]] + (f" (name rule {link['rule']})" if link["rule"] else "")
    return f"{link['a']} and {link['b']} are linked by {how}. {_state(link)}"


def to_answer(r: IdentityCheckpoint) -> Answer:
    """The checkpoint as an Answer, with no model. Caveats and sources are the ones the functions returned."""
    d = checkpoint_to_dict(r)
    caveats = [CaveatOut(code=code, text=text) for code, text in dict.fromkeys((c["code"], c["text"]) for c in d["caveats"])]
    if d["status"] == "not_found":
        return Answer(kind="not_found", summary=f"No landlord record is named {d['name']} in the data.", caveats=caveats)
    if d["status"] == "ambiguous_name":
        groups = "; ".join(f"{k} ({n} lots)" for k, n in d["candidates"])
        return Answer(kind="clarification", caveats=caveats, summary=(
            f"Landlord records named {d['name']} fall into {len(d['candidates'])} separate identity groups: {groups}. "
            "Say which group you mean; none was chosen."))
    eff, links = d["portfolio_effect"], d["links"]
    held, decided = eff["as_held"], eff["as_decided"]
    waiting = sum(x["state"] == "awaiting" for x in links)
    summary = (f"{d['anchor']['key']}: as held in the graph, {_counts(held)} across {d['anchor']['records']} landlord "
               f"record{'s' if d['anchor']['records'] != 1 else ''}. ")
    summary += (f"{len(links)} possible link{'s' if len(links) != 1 else ''} to other landlord records, {waiting} awaiting a decision. "
                if links else "No other landlord record is linked to it by a shared business address or name. ")
    summary += f"After the researcher's decisions: {_counts(decided)}." if d["decisions"] else "No decision has been made yet."
    facts = [Fact(statement=_link_statement(x), evidence=[Evidence(section="links", data=x)]) for x in links]
    facts.append(Fact(statement=f"As held in the graph: {_counts(held)}. After the researcher's decisions: {_counts(decided)}.",
                      evidence=[Evidence(section="portfolio_effect", data=eff)]))
    for iss in d["issues"]:
        facts.append(Fact(statement=f"A decision on {iss['linkId']} was not applied: {iss['text']}", evidence=[Evidence(section="decisions", data=iss)]))
    return Answer(kind="identity_checkpoint", summary=summary, facts=facts, caveats=caveats, sources=d["sources"])
