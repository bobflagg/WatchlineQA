"""Run the report from the command line: `make report ADDRESS="..." [DECISIONS=file.json]`. No model is called.

Without a decisions file it stops at the pause and prints the leads. With one it answers the pause itself and writes the report, which is how the backup run for a talk is
made and how a report is rebuilt from its decision log. Both outputs are compared byte for byte when a report is run twice.
"""
import argparse
import json
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from watchline.report.export import decisions_file, write_report
from watchline.report.graph import CHOOSE_LANDLORD, ReportDeps, build_report_graph, pending


def run_report(deps: ReportDeps, address: str, *, borough: str | None = None, zip5: str | None = None, decisions: list[dict] | None = None,
               landlord: str | None = None, label: str = "") -> dict:
    """Run the graph. Returns {"status": "done", "report": ...} or {"status": "paused", "prompt": ...}. A bad answer raises ValueError instead of asking again."""
    graph = build_report_graph(deps, InMemorySaver())
    cfg = {"configurable": {"thread_id": "report"}}
    result = graph.invoke({"text": address, "borough": borough, "zip5": zip5, "generated_at": label}, cfg)
    for _ in range(3):                               # at most the landlord picker and the decisions
        if "report" in result:
            return {"status": "done", "report": result["report"]}
        (prompt,) = pending(result)
        if prompt.get("error"):
            raise ValueError(prompt["error"])
        if prompt["kind"] == CHOOSE_LANDLORD and landlord is not None:
            answer = {"name": landlord}
        elif prompt["kind"] != CHOOSE_LANDLORD and decisions is not None:
            answer = {"decisions": decisions}
        else:
            return {"status": "paused", "prompt": prompt}
        result = graph.invoke(Command(resume=answer), cfg)
    raise ValueError("the report is still waiting after its answers")


def main(argv: list[str] | None = None, deps: ReportDeps | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the landlord report for a building address (no model is called).")
    ap.add_argument("address")
    ap.add_argument("--borough")
    ap.add_argument("--zip")
    ap.add_argument("--decisions", help="a JSON list of decisions: answers the pause and writes the report")
    ap.add_argument("--landlord", help="the landlord name to check, when several records cover the lot")
    ap.add_argument("--label", default="", help="a label printed in the report header (for example the date); never taken from the clock")
    ap.add_argument("--out", default="build/reports")
    ap.add_argument("--takeaway", help="a text file with the researcher's takeaway")
    a = ap.parse_args(argv)
    close = None
    if deps is None:
        from watchline.agent.chat import StartupError, connect_all
        try:
            client, graph, pg, rg, ig, close = connect_all()
        except StartupError as e:
            print(f"Cannot start: {e}", file=sys.stderr)
            return 1
        deps = ReportDeps(client, graph, pg, rg, ig)
    try:
        decisions = decisions_file(a.decisions) if a.decisions else None
        out = run_report(deps, a.address, borough=a.borough, zip5=a.zip, decisions=decisions, landlord=a.landlord, label=a.label)
    except (ValueError, OSError) as e:
        print(f"Cannot build the report: {e}", file=sys.stderr)
        return 1
    finally:
        if close:
            close()
    if out["status"] == "paused":
        p = out["prompt"]
        print(json.dumps(p, indent=2, default=str))
        print("\nThe report is waiting. Run it again with --decisions FILE (a JSON list of decisions) or --landlord NAME.", file=sys.stderr)
        return 2
    report = out["report"]
    md, log = write_report(report, a.out, Path(a.takeaway).read_text() if a.takeaway else None)
    print(f"{md}\n{log}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
