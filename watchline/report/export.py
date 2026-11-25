"""The report as Markdown, and its files. No model, no clock: the same report gives the same text, byte for byte.

The sections are grouped under the PESP guide's five questions, each with its own caveats and sources. The researcher's takeaway, if any, is added at the end and labelled as
theirs. The decision log is written beside the report so the report can be rebuilt from the same graph snapshot and the same decisions.
"""
import json
import re
from pathlib import Path

from watchline.agent.answer import Answer, render_markdown

HOW_TO_READ = (
    "This report is built from the Watchline graph by fixed templates. The same records and the same decisions give the same report, and no generated text is in it. "
    "A lead is a connection the records suggest (a shared address, a similar name, names listed together on a registration); it is not a finding that two parties are one. "
    "Violations and cases are what was cited or brought, not findings of fault. A deed with an amount of 0 is not a sale."
)


def slug(address: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-") or "report"


def render_report(report: dict, takeaway: str | None = None) -> str:
    """The Markdown for a finished report (or the reason one could not be made)."""
    if report["status"] == "needs_input":
        n = report["needs_input"]
        lines = [f"# Landlord report: {report['typed']}", "", "The report could not be built for this address.", "", f"- {n['message']}"]
        if n.get("candidates"):
            lines += ["- Candidate streets: " + ", ".join(n["candidates"])]
        return "\n".join(lines) + "\n"
    out = [f"# Landlord report: {report['address']}", "",
           f"Tax lot {report['bbl']} · {report.get('generated_at') or 'not dated'} · landlord record checked: {report.get('landlord') or 'none (no landlord record covers this lot)'}", "",
           f"**How to read this report.** {HOW_TO_READ}", "", "**Sources and their snapshots**", *(f"- {s}" for s in report["sources"]), ""]
    question = None
    for sec in report["sections"]:
        if sec["question"] != question:
            question = sec["question"]
            out += [f"## {question}", ""]
        out += [f"### {sec['title']} (guide {'steps' if ' and ' in sec['step'] else 'step'} {sec['step']})", "", render_markdown(Answer(**sec["answer"])), ""]
    out += ["## Decisions", ""]
    if report["decisions"]:
        out += ["| Link | Decision | Decided by | Date | Note |", "|---|---|---|---|---|",
                *(f"| {d['linkId']} | {d['decision']} | {d['decidedBy']} | {d['decidedAt']} | {d.get('note') or ''} |" for d in report["decisions"])]
        out += ["", "The decision log is saved with the report (decisions.json). Decisions are the researcher's own inference, not findings in the records."]
    else:
        out += ["No decision was made on any lead."]
    out += ["", "## The researcher's takeaway", "", ("Written by the researcher, not generated:\n\n" + takeaway.strip()) if takeaway and takeaway.strip() else "Not written yet."]
    return "\n".join(out) + "\n"


def write_report(report: dict, root: str | Path = "build/reports", takeaway: str | None = None) -> tuple[Path, Path]:
    """Write report.md and decisions.json into <root>/<address slug>/ and return their paths."""
    folder = Path(root) / slug(report["typed"] if report["status"] == "needs_input" else report["address"])
    folder.mkdir(parents=True, exist_ok=True)
    md, log = folder / "report.md", folder / "decisions.json"
    md.write_text(render_report(report, takeaway))
    log.write_text(report.get("decision_log") or "[]")
    return md, log


def decisions_file(path: str | Path) -> list[dict]:
    """The decisions saved with an earlier report (or written by hand): a JSON list. Raises ValueError if it is not one."""
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("the decisions file must hold a JSON list")
    return data
