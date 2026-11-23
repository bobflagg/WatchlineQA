"""The answer contract. Every answer is data first: a kind, a summary, facts with evidence, caveats and sources.

The model fills only `ModelAnswer`: what kind of answer this is, a short summary, and facts that point at the tool data they rest
on. Code builds the rest (`assemble`): it copies the pointed-at data in as evidence, and attaches every caveat and source the tools
returned, verbatim, so the model cannot drop one. `render_markdown` gives the terminal chat (and any plain display) the same
answer as text. Layout and styling belong to a UI, not here.
"""
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["profile", "clarification", "not_found", "refusal", "error"]
Section = Literal["lookup", "resolution", "characteristics", "counts", "buildings", "totals"]


# ---- what the model fills -----------------------------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    section: Section = Field(description="Which part of the tool result the statement rests on.")
    bin: str | None = Field(default=None, description=(
        "The building's BIN, to point at one building under section 'buildings'. Without it, 'buildings' means the whole list "
        "(use that to say no building is listed)."))


class ModelFact(BaseModel):
    statement: str = Field(description="One claim the records support, in one sentence. Every number must come from the tool result.")
    evidence: list[EvidenceRef] = Field(default_factory=list, description="Where in the tool result this claim comes from.")


class ModelAnswer(BaseModel):
    """The answer to the user. Caveats and sources are attached automatically from the tool results; do not write them."""
    kind: Kind = Field(description=(
        "profile: a lot was found and profiled. clarification: you need the borough or ZIP, a house number and street, or a choice "
        "among candidate streets. not_found: no lot matched. refusal: you were asked to judge fault or for something outside the "
        "records. error: the lookup failed."))
    summary: str = Field(description="One to three plain sentences that answer the question asked. No caveats; they are attached.")
    facts: list[ModelFact] = Field(default_factory=list, description="The specific things the records show, one claim each.")


# ---- what code builds ---------------------------------------------------------------------------------------------------

class Evidence(BaseModel):
    section: Section
    bin: str | None = None
    data: Any                       # the tool's own data for that section, copied by code


class Fact(BaseModel):
    statement: str
    evidence: list[Evidence] = Field(default_factory=list)
    unresolved: list[EvidenceRef] = Field(default_factory=list)   # references that point at nothing in the tool results


class CaveatOut(BaseModel):
    code: str
    text: str


class Answer(BaseModel):
    kind: Kind
    summary: str
    facts: list[Fact] = Field(default_factory=list)
    caveats: list[CaveatOut] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @property
    def model_text(self) -> str:
        """What the model alone wrote: the summary and the fact statements. Caveats are not included on purpose."""
        return "\n".join([self.summary, *(f.statement for f in self.facts)])

    @property
    def caveat_codes(self) -> set[str]:
        return {c.code for c in self.caveats}


_SECTION_KEY = {"resolution": "resolution", "characteristics": "characteristics", "counts": "counts",
                "totals": "totals_across_all_listed_buildings"}


def _resolve(ref: EvidenceRef, results: list[dict]) -> tuple[Evidence, int] | None:
    """The tool data a reference points at, and the index of the result it came from, or None.

    The latest result that has it wins; a BIN picks the result that lists it. `buildings` without a BIN is the whole list, which may
    be empty (that is how an absence is evidenced). `lookup` is the tool's own status and message, for answers that ask a question.
    """
    for i in reversed(range(len(results))):
        out = results[i]
        if ref.section == "lookup":
            if out.get("status"):
                return Evidence(section="lookup", data={"status": out["status"], "message": out.get("message")}), i
        elif ref.section == "buildings":
            if ref.bin is None:
                if "buildings" in out and out.get("resolution"):
                    return Evidence(section="buildings", data=out["buildings"]), i
            else:
                for b in out.get("buildings") or []:
                    if b.get("bin") == ref.bin:
                        return Evidence(section="buildings", bin=ref.bin, data=b), i
        else:
            data = out.get(_SECTION_KEY[ref.section])
            if data:                                    # None, [] and {} mean the tool had nothing for this section
                return Evidence(section=ref.section, data=data), i
    return None


def assemble(model: ModelAnswer, tool_results: list[dict], earlier: list[dict] = ()) -> Answer:
    """Pure: the model's answer plus the tool results in, the full Answer out. Caveats and sources come only from the tools.

    `tool_results` are this turn's. `earlier` are results from earlier turns of the same conversation: a follow-up may rest on
    them, so evidence can point at them, and a result that evidence points at contributes its caveats and sources too.
    """
    results = [*earlier, *tool_results]
    used = set(range(len(earlier), len(results)))        # this turn's results always count
    facts = []
    for f in model.facts:
        resolved, unresolved = [], []
        for ref in f.evidence:
            hit = _resolve(ref, results)
            if hit:
                resolved.append(hit[0])
                used.add(hit[1])
            else:
                unresolved.append(ref)
        facts.append(Fact(statement=f.statement, evidence=resolved, unresolved=unresolved))
    caveats: list[CaveatOut] = []
    sources: list[str] = []
    for i in sorted(used):
        out = results[i]
        for c in out.get("caveats") or []:
            item = CaveatOut(code=c["code"], text=c["text"])
            if item not in caveats:
                caveats.append(item)
        for src in out.get("sources") or []:
            if src not in sources:
                sources.append(src)
    return Answer(kind=model.kind, summary=model.summary, facts=facts, caveats=caveats, sources=sources)


def _tag(ev: Evidence | EvidenceRef) -> str:
    return f"{ev.section} BIN {ev.bin}" if ev.bin and ev.section == "buildings" else ev.section


def render_markdown(a: Answer) -> str:
    """The answer as plain markdown: summary, facts with where they come from, caveats, sources."""
    parts = [a.summary.strip()]
    if a.facts:
        lines = []
        for f in a.facts:
            tags = [_tag(e) for e in f.evidence] + [f"unverified reference: {_tag(r)}" for r in f.unresolved]
            lines.append(f"- {f.statement.strip()}" + (f" _({'; '.join(tags)})_" if tags else ""))
        parts.append("**What the records show**\n" + "\n".join(lines))
    if a.caveats:
        parts.append("**Caveats**\n" + "\n".join(f"- {c.text}" for c in a.caveats))
    if a.sources:
        parts.append("**Sources**\n" + "\n".join(f"- {s}" for s in a.sources))
    return "\n\n".join(parts)


# ---- a guard against numbers the records never gave ---------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUMBER.findall(text):
        out.add(m.replace(",", "").rstrip("."))
    return out


def ungrounded_numbers(text: str, tool_results: list[dict], question: str = "") -> list[str]:
    """Numbers in `text` that appear nowhere in the tool results or the user's question.

    The rules say never add counts into one number. A sum the tool did not provide is, by construction, a number the records do not
    contain, so it shows up here. It cannot catch a sum that happens to equal a recorded number; the judge is the other guard.
    """
    grounded = _numbers(json.dumps(tool_results, default=str)) | _numbers(question)
    return sorted(n for n in _numbers(text) if n not in grounded)
