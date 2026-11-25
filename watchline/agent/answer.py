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

ModelKind = Literal["profile", "registration", "ownership_comparison", "timeline", "contacts", "violations", "litigation", "clarification", "not_found", "refusal", "error"]
Kind = Literal["profile", "registration", "ownership_comparison", "timeline", "contacts", "identity_checkpoint", "violations", "litigation", "not_covered", "clarification", "not_found", "refusal", "error"]
ModelSection = Literal["lookup", "lot", "resolution", "characteristics", "counts", "buildings", "totals", "registrations", "deeds", "owners", "comparison", "timeline", "timeline_counts", "contacts", "violations", "violations_rate", "cases", "case_counts", "registered_owners"]   # what the model may cite
Section = Literal["lookup", "lot", "resolution", "characteristics", "counts", "buildings", "totals", "registrations", "deeds", "owners", "comparison", "timeline", "timeline_counts", "contacts", "links", "decisions", "portfolio_effect", "violations", "violations_rate", "cases", "case_counts", "registered_owners"]


# ---- what the model fills -----------------------------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    section: ModelSection = Field(description="Which part of the tool result the statement rests on.")
    bin: str | None = Field(default=None, description=(
        "The building's BIN, to point at one building under section 'buildings', 'registrations', 'contacts' or 'violations'. Without it, the section "
        "means the whole list (use that to say no building or no registration is listed)."))
    bbl: str | None = Field(default=None, description=(
        "The tax lot (BBL) the data is about. Give it when the conversation has looked up more than one lot."))


class ModelFact(BaseModel):
    statement: str = Field(description="One claim the records support, in one sentence. Every number must come from the tool result.")
    evidence: list[EvidenceRef] = Field(default_factory=list, description="Where in the tool result this claim comes from.")


class ModelAnswer(BaseModel):
    """The answer to the user. Caveats and sources are attached automatically from the tool results; do not write them."""
    kind: ModelKind = Field(description=(
        "profile: a lot was found and profiled. registration: HPD registrations and registered owners were looked up for a lot. ownership_comparison: the most recent deed(s) and their grantees were compared with the HPD registered owners. timeline: every recorded deed of a lot was listed with its dates, amount, grantors and grantees. violations: open and closed violations of a lot's buildings by class, with the oldest open inspection and the rate per unit. litigation: Housing Court cases of a lot's buildings with respondents and any harassment finding. contacts: the HPD contacts of each registration (agent, officers, site manager and so on) were listed with their recorded roles. clarification: you need the borough or ZIP, a house number and street, or a choice "
        "among candidate streets. not_found: no lot matched. refusal: you were asked to judge fault or for something outside the "
        "records. error: the lookup failed."))
    summary: str = Field(description="One to three plain sentences that answer the question asked. No caveats; they are attached.")
    facts: list[ModelFact] = Field(default_factory=list, description="The specific things the records show, one claim each.")


# ---- what code builds ---------------------------------------------------------------------------------------------------

class Evidence(BaseModel):
    section: Section
    bin: str | None = None
    bbl: str | None = None          # the lot of the tool result this came from, so a reader can see which lot it is about
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


def _bbl(out: dict) -> str | None:
    return (out.get("resolution") or {}).get("bbl")


def _resolve(ref: EvidenceRef, results: list[dict], floor: int = 0) -> tuple[Evidence, int] | None:
    """The tool data a reference points at, and the index of the result it came from, or None.

    The latest result that has it wins (results before `floor` are not searched); a BIN picks the result that lists it, and a BBL
    picks the result about that lot. `buildings` without a BIN is the whole list, which may be empty (that is how an absence is
    evidenced). `lookup` is the tool's own status and message, for answers that ask a question.
    """
    for i in reversed(range(floor, len(results))):
        out = results[i]
        if ref.bbl is not None and _bbl(out) != ref.bbl:
            continue
        if ref.section == "lookup":
            if out.get("status"):
                return Evidence(section="lookup", bbl=_bbl(out), data={"status": out["status"], "message": out.get("message")}), i
        elif ref.section == "lot":                            # the lot's own values (year built, class, units), as a tool lists them
            if out.get("lot") is not None and out.get("resolution"):
                return Evidence(section="lot", bbl=_bbl(out), data=out["lot"]), i
        elif ref.section == "violations" and ref.bin is not None:
            for b in out.get("violations") or []:
                if b.get("bin") == ref.bin and out.get("resolution"):
                    return Evidence(section="violations", bin=ref.bin, bbl=_bbl(out), data=b), i
        elif ref.section in ("registrations", "contacts"):
            blist = out.get("registration_buildings" if ref.section == "registrations" else "contact_buildings")
            if blist is None or not out.get("resolution"):
                continue
            if ref.bin is None:
                return Evidence(section=ref.section, bbl=_bbl(out), data=blist), i
            for b in blist:
                if b.get("bin") == ref.bin:
                    return Evidence(section=ref.section, bin=ref.bin, bbl=_bbl(out), data=b), i
        elif ref.section in ("deeds", "owners", "comparison", "timeline", "timeline_counts", "violations", "violations_rate", "cases", "case_counts", "registered_owners"):
            lst = out.get(ref.section)                    # [] is evidence of absence, so only a missing key skips the result
            if lst is not None and out.get("resolution") and out.get("lot") is not None:   # absence needs a lot that was read
                return Evidence(section=ref.section, bbl=_bbl(out), data=lst), i
        elif ref.section == "buildings":
            if ref.bin is None:
                if "buildings" in out and out.get("resolution"):
                    return Evidence(section="buildings", bbl=_bbl(out), data=out["buildings"]), i
            else:
                for b in out.get("buildings") or []:
                    if b.get("bin") == ref.bin:
                        return Evidence(section="buildings", bin=ref.bin, bbl=_bbl(out), data=b), i
        else:
            data = out.get(_SECTION_KEY.get(ref.section, ref.section))        # a section no tool feeds finds nothing: the fact is shown as unresolved
            if data:                                    # None, [] and {} mean the tool had nothing for this section
                return Evidence(section=ref.section, bbl=_bbl(out), data=data), i
    return None


def assemble(model: ModelAnswer, tool_results: list[dict], earlier: list[dict] = ()) -> Answer:
    """Pure: the model's answer plus the tool results in, the full Answer out. Caveats and sources come only from the tools.

    `tool_results` are this turn's. `earlier` are results from earlier turns of the same conversation: a follow-up may rest on
    them, so evidence can point at them, and a result that evidence points at contributes its caveats and sources too. A follow-up
    that makes no lookup rests on the latest earlier result whether or not its facts cite anything. If this turn's lookup failed
    (needs a borough, invalid input, error), its references never fall through to an earlier lot.
    """
    results = [*earlier, *tool_results]
    n_earlier = len(earlier)
    used = set(range(n_earlier, len(results)))           # this turn's results always count
    if not tool_results and earlier:
        used.add(n_earlier - 1)
    floor = 0
    if any(r.get("status") not in ("ok", None) for r in tool_results):
        floor = n_earlier                                 # a failed lookup this turn: do not answer from an earlier lot
    facts = []
    for f in model.facts:
        resolved, unresolved = [], []
        for ref in f.evidence:
            hit = _resolve(ref, results, floor)
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
    return f"{ev.section} BIN {ev.bin}" if ev.bin and ev.section in ("buildings", "registrations", "contacts", "violations") else ev.section


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

_DATA_KEYS = ("resolution", "lot", "characteristics", "counts", "buildings", "buildings_listed", "totals_across_all_listed_buildings",
              "registration_buildings", "contact_buildings", "deeds", "owners", "comparison", "timeline", "timeline_counts",
              "violations", "violations_rate", "cases", "case_counts", "registered_owners")
_WORDS = {w: str(n) for n, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
    "nineteen twenty".split())}
_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90"})
_WORD_NUMBER = re.compile(r"\b(" + "|".join(w for w in _WORDS if w != "one") + r")\b", re.I)   # "one" is too common in prose
_CODE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d+[A-Za-z]\w*)\b")      # 2026-05-29, 26v1, 25b: compared whole, against the sources
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _plain(n: str) -> str:
    n = n.replace(",", "").rstrip(".")
    return n[:-2] if n.endswith(".0") else n


def _without_prose(x):
    """x with every 'source' string removed (they name releases, not data), at any depth."""
    if isinstance(x, dict):
        return {k: _without_prose(v) for k, v in x.items() if k != "source"}
    if isinstance(x, list):
        return [_without_prose(v) for v in x]
    return x


def _data_only(x):
    """A tool result without its prose (caveats, sources, message): numbers in those do not make a number grounded."""
    if isinstance(x, dict) and ("status" in x or any(k in x for k in _DATA_KEYS)):
        return _without_prose({k: x[k] for k in _DATA_KEYS if k in x})
    return _without_prose(x)


def _bbl_parts(text: str) -> set[str]:
    out = set()
    for bbl in re.findall(r"\b\d{10}\b", text):
        out |= {bbl[0], str(int(bbl[1:6])), str(int(bbl[6:]))}      # borough, block, lot
    return out


_ORDINAL = re.compile(r"(?<=\d)(?:st|nd|rd|th)\b", re.I)      # 54th is 54


def _numbers(text: str) -> set[str]:
    return {_plain(m) for m in _NUMBER.findall(text)}


def _candidate_counts(results: list[dict]) -> set[str]:
    """How many candidate streets an ambiguous lookup listed: counting them is not inventing a number."""
    return {str(len(c)) for r in results if isinstance(r, dict) for c in [(r.get("resolution") or {}).get("candidates")] if c}


def ungrounded_numbers(text: str, tool_results: list[dict], question: str = "") -> list[str]:
    """Numbers (digits, or a number word such as "six") in `text` that appear nowhere in the tool *data* or the user's question.

    The rules say never add counts into one number. A sum the tool did not provide is, by construction, a number the records do not
    contain, so it shows up here. Only data fields ground a number, not caveat or source text, so "release 25b" does not make 25
    acceptable. Codes such as 26v1 and 2026-05-29 are compared whole against the sources. It cannot catch a sum that happens to
    equal a recorded number; the judge is the other guard.
    """
    data = _ORDINAL.sub("", json.dumps([_data_only(r) for r in tool_results], default=str))
    text, question = _ORDINAL.sub("", text), _ORDINAL.sub("", question)
    sources = " ".join(s for r in tool_results if isinstance(r, dict) for s in r.get("sources") or [])
    grounded = {_plain(n) for n in _numbers(data) | _numbers(question) | _bbl_parts(data + " " + question)}
    grounded |= _candidate_counts(tool_results)
    codes = {c.lower() for c in _CODE.findall(sources) + _CODE.findall(data) + _CODE.findall(question)}
    stray = []
    for code in _CODE.findall(text):
        if code.lower() not in codes:
            stray.append(code)
    rest = _CODE.sub(" ", text)
    for n in sorted(_numbers(rest) - grounded):
        stray.append(n)
    for w in _WORD_NUMBER.findall(rest):
        if _WORDS[w.lower()] not in grounded and w.lower() not in stray:
            stray.append(w.lower())
    return sorted(stray)
