"""The report as Markdown and files, and the command line. Fake rows; no graph, no model."""
import json

import pytest
from test_conditions import case, g
from test_contacts import crow
from test_deeds import drow
from test_identity_graph import FakeIG
from test_profile import BUILDINGS
from test_report_full import AllReads, FakeClient, FakeGraph, FakePG, ReportDeps, accept, identity_rows, resolved
from test_timeline import trow

from watchline.report import export as X
from watchline.report import run as R


def deps(**kw):
    return ReportDeps(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS),
                      AllReads(deeds=[drow()], timeline=[trow()], contacts=[crow()], groups=[g()], cases=[case()]), FakeIG(**identity_rows(**kw)))


DECISIONS = accept()["decisions"]


def finished(**kw):
    out = R.run_report(deps(**kw), "1 Main St", borough="Manhattan", decisions=DECISIONS, label="2026-12-01 demo")
    assert out["status"] == "done"
    return out["report"]


# ---- the Markdown ---------------------------------------------------------------------------------------------------------

def test_the_report_has_the_header_the_five_questions_the_sections_and_the_decisions():
    md = X.render_report(finished(), takeaway="The registration names both spellings, so I treat them as one operator.")
    assert md.startswith("# Landlord report: 1 MAIN ST\n")          # the address as the city matched it
    assert "Tax lot 1000010001 · 2026-12-01 demo · landlord record checked: ACME OWNER" in md
    assert "no generated text is in it" in md and "A deed with an amount of 0 is not a sale." in md
    heads = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert heads == ["## About this building", "## Who is my landlord?", "## How many properties and where?", "## Do they hold or sell?",
                     "## What are the conditions?", "## Is there news?", "## Decisions", "## The researcher's takeaway"]
    assert "### Registered owner and contacts (guide step 3)" in md and "### Housing Court cases (guide step 8)" in md
    assert "### Related landlord records and the portfolio (guide steps 6 and 7)" in md
    assert "Not yet covered: Entity research." in md and "Not yet covered: Web research." in md
    assert "| ACME OWNER\\|ACME OWNR | accept | researcher | 2026-12-01 | same office |" in md
    assert "Written by the researcher, not generated:\n\nThe registration names both spellings" in md
    assert "**Caveats**" in md and "**Sources**" in md and "**What the records show**" in md


def test_every_caveat_and_source_of_every_section_is_in_the_markdown():
    rep = finished()
    md = X.render_report(rep)
    for sec in rep["sections"]:
        for c in sec["answer"]["caveats"]:
            assert c["text"].strip() in md, (sec["key"], c["code"])
        for s in sec["answer"]["sources"]:
            assert s in md
    assert all(s in md for s in rep["sources"])


def test_a_report_with_no_decision_says_so_and_no_takeaway_says_not_written():
    out = R.run_report(deps(lead=False), "1 Main St", borough="Manhattan")
    md = X.render_report(out["report"])
    assert "No decision was made on any lead." in md and "Not written yet." in md


def test_the_same_report_gives_the_same_text_byte_for_byte():
    assert X.render_report(finished()) == X.render_report(finished())


def test_a_report_that_could_not_be_built_says_why():
    out = R.run_report(deps(), "1 Main St")                       # no borough
    md = X.render_report(out["report"])
    assert out["status"] == "done" and out["report"]["status"] == "needs_input"
    assert "could not be built" in md and "Give the borough or a ZIP" in md and "## " not in md


# ---- the files and the command ---------------------------------------------------------------------------------------------

def test_the_files_are_written_to_a_folder_named_for_the_address(tmp_path):
    md, log = X.write_report(finished(), tmp_path, takeaway="x")
    assert md == tmp_path / "1-main-st" / "report.md" and log == tmp_path / "1-main-st" / "decisions.json"
    assert md.read_text().startswith("# Landlord report: 1 MAIN ST")
    saved = json.loads(log.read_text())
    assert [(d["linkId"], d["decision"], d["decidedBy"], d["decidedAt"], d["note"]) for d in saved] == [("ACME OWNER|ACME OWNR", "accept", "researcher", "2026-12-01", "same office")]
    assert X.slug("74 Clinton Place, Bronx") == "74-clinton-place-bronx" and X.slug("???") == "report"


def test_the_decision_log_rebuilds_the_same_report(tmp_path):
    first = finished()
    _, log = X.write_report(first, tmp_path)
    again = R.run_report(deps(), "1 Main St", borough="Manhattan", decisions=X.decisions_file(log), label="2026-12-01 demo")["report"]
    assert X.render_report(again) == X.render_report(first)


def test_run_report_stops_at_the_pause_without_decisions_and_at_a_bad_answer():
    out = R.run_report(deps(), "1 Main St", borough="Manhattan")
    assert out["status"] == "paused" and out["prompt"]["kind"] == "identity_checkpoint_decision"
    with pytest.raises(ValueError, match="must be accept or reject"):
        R.run_report(deps(), "1 Main St", borough="Manhattan", decisions=accept(what="approve")["decisions"])


def test_the_command_writes_the_files_or_says_what_it_is_waiting_for(tmp_path, capsys):
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps(DECISIONS))
    assert R.main(["1 Main St", "--borough", "Manhattan", "--decisions", str(dec), "--out", str(tmp_path / "out"), "--label", "demo"], deps=deps()) == 0
    assert (tmp_path / "out" / "1-main-st" / "report.md").exists() and "report.md" in capsys.readouterr().out
    assert R.main(["1 Main St", "--borough", "Manhattan", "--out", str(tmp_path / "out2")], deps=deps()) == 2          # paused: nothing written
    cap = capsys.readouterr()
    assert "identity_checkpoint_decision" in cap.out and "--decisions" in cap.err and not (tmp_path / "out2").exists()
    assert R.main(["1 Main St", "--decisions", str(tmp_path / "missing.json")], deps=deps()) == 1


def test_a_takeaway_file_is_added_and_labelled(tmp_path):
    t = tmp_path / "t.txt"
    t.write_text("My reading.")
    dec = tmp_path / "d.json"
    dec.write_text(json.dumps(DECISIONS))
    R.main(["1 Main St", "--borough", "Manhattan", "--decisions", str(dec), "--out", str(tmp_path), "--takeaway", str(t)], deps=deps())
    assert "Written by the researcher, not generated:\n\nMy reading." in (tmp_path / "1-main-st" / "report.md").read_text()
