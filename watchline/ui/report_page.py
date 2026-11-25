"""The landlord report page: enter a building address, read the sections, decide on the leads, download the report. No model is called.

The page takes its dependencies as an argument (`ReportDeps`), so tests run it on fakes and `report_app.py` runs it on the real graph. It keeps the
graph and its last result in session state, answers the graph's pauses from widgets, and renders every section with `render_answer`, so no caveat can be dropped.
"""
import uuid
from datetime import date

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from watchline.agent.answer import Answer
from watchline.report.export import render_report
from watchline.report.graph import CHOOSE_LANDLORD, SECTIONS, ReportDeps, build_report_graph
from watchline.ui.render import render_answer

ROLES = ("researcher", "organizer", "legal staff")
CHOICES = ("Decide later", "Accept", "Reject")
INTRO = ("A report on one building address, built from the Watchline records by fixed templates, in the order of the research guide. No text in it is generated. "
         "Leads are connections the records suggest; you decide whether to accept each one, and your decisions are saved with the report.")


def _lots(f: dict) -> str:
    return f"{f['lots']} lot{'s' if f['lots'] != 1 else ''}"


def _units(f: dict) -> str:
    return f"{f['units']} residential unit{'s' if f['units'] != 1 else ''}"


def _config() -> dict:
    return {"configurable": {"thread_id": st.session_state.rp_thread}}


def _start(deps: ReportDeps, address: str, label: str) -> None:
    ss = st.session_state
    ss.rp_thread = str(uuid.uuid4())
    ss.rp_graph = build_report_graph(deps, InMemorySaver())
    ss.rp_result = ss.rp_graph.invoke({"text": address.strip(), "generated_at": label.strip()}, _config())


def _resume(answer: dict) -> None:
    ss = st.session_state
    ss.rp_result = ss.rp_graph.invoke(Command(resume=answer), _config())


def _decisions(links: list[dict], today: str) -> dict:
    ss = st.session_state
    out = []
    for i, ln in enumerate(links):
        choice = ss.get(f"rp_choice_{i}", CHOICES[0])
        if choice != CHOICES[0]:
            out.append({"linkId": ln["linkId"], "decision": choice.lower(), "decidedBy": ss.get("rp_role", ROLES[0]), "decidedAt": today,
                        **({"note": ss[f"rp_note_{i}"]} if ss.get(f"rp_note_{i}", "").strip() else {})})
    return {"decisions": out}


def _sections_so_far(parts: dict) -> list[dict]:
    return [{"key": k, "step": step, "question": question, "title": title, "answer": parts[k]["answer"]} for k, step, question, title in SECTIONS if k in parts]


def _show_sections(sections: list[dict]) -> None:
    question = None
    for sec in sections:
        if sec["question"] != question:
            question = sec["question"]
            st.header(question, divider="gray")
        st.subheader(sec["title"])
        st.caption(f"Guide {'steps' if ' and ' in sec['step'] else 'step'} {sec['step']}")
        if sec["answer"]["kind"] == "not_covered":
            st.badge("Not yet covered", color="gray")
        render_answer(Answer(**sec["answer"]))


def _show_lead(i: int, ln: dict) -> None:
    with st.container(border=True):
        st.badge("Lead", color="orange")
        st.markdown(f"**{ln['a']}** and **{ln['b']}**")
        st.caption("Joined by: " + ", ".join({"address": "a shared business address", "name": "a similar name", "contact": "names listed together on an HPD registration",
                                              "identity": "an identity link"}[k] for k in ln["kinds"]))
        for e in ln["evidence"]:
            st.markdown(f"- {'**Set aside** (' + str(e['reason']) + '): ' if e['setAside'] else '**Used:** '}{e['text']}")
        for line in ln["against"]:
            st.markdown(f"- Against: {line}")
        st.radio("Your decision", CHOICES, key=f"rp_choice_{i}", horizontal=True)
        st.text_input("Note (saved with the decision)", key=f"rp_note_{i}")


def _show_pause(prompt: dict, today: str) -> None:
    if prompt.get("error"):
        st.error(prompt["error"])
    if prompt["kind"] == CHOOSE_LANDLORD:
        st.subheader("Which landlord record should the report check?")
        st.caption("More than one landlord name covers this lot. None is chosen for you.")
        st.selectbox("Landlord name", prompt["names"], key="rp_landlord")
        st.button("Check this landlord", key="rp_pick", on_click=lambda: _resume({"name": st.session_state.rp_landlord}))
        return
    held = prompt["portfolio_effect"]["as_held"]
    st.subheader("Your decision on the leads")
    st.markdown(f"As held in the graph, the portfolio is **{_lots(held)}** and **{_units(held)}**. Each lead below is a connection the records "
                "suggest, not a finding. Accepting one adds the other party's lots to the portfolio as your own inference.")
    for i, ln in enumerate(prompt["links"]):
        _show_lead(i, ln)
    st.selectbox("Decided by (a role, not a name)", ROLES, key="rp_role")
    st.button("Save my decisions and finish the report", key="rp_submit", type="primary", on_click=lambda: _resume(_decisions(prompt["links"], today)))


def _show_final(report: dict) -> None:
    if report["status"] == "needs_input":
        st.warning(report["needs_input"]["message"], title="The report could not be built for this address")
        if report["needs_input"].get("candidates"):
            st.markdown("Candidate streets: " + ", ".join(report["needs_input"]["candidates"]))
        return
    st.success(f"Report for {report['address']} (tax lot {report['bbl']}); landlord record checked: {report['landlord'] or 'none, no record covers this lot'}.")
    eff = (report.get("checkpoint") or {}).get("portfolio_effect")
    if eff:
        a, b = st.columns(2)
        for col, label, f in ((a, "Portfolio as held in the graph", eff["as_held"]), (b, "After your decisions", eff["as_decided"])):
            with col:
                st.metric(label, _lots(f), border=True)
                st.caption(_units(f))
    _show_sections(report["sections"])
    st.header("Your takeaway", divider="gray")
    st.text_area("Written in your own words; it is saved in the report and labelled as yours", key="rp_takeaway")
    takeaway = st.session_state.get("rp_takeaway", "")
    st.download_button("Download the report (Markdown)", render_report(report, takeaway), file_name="report.md", mime="text/markdown", key="rp_dl_report")
    st.download_button("Download the decision log (JSON)", report["decision_log"], file_name="decisions.json", mime="application/json", key="rp_dl_log")


def render_report_page(deps: ReportDeps, *, today: str | None = None) -> None:
    """The whole page. `today` is the date recorded on decisions (the page's own clock unless a test passes one)."""
    today = today or date.today().isoformat()
    st.title("Landlord report")
    st.caption(INTRO)
    with st.form("rp_form"):
        st.text_input("Building address", key="rp_address", placeholder="74 Clinton Place, Bronx")
        st.text_input("Report label (printed in the header, for example the date)", key="rp_label")
        go = st.form_submit_button("Build the report", type="primary", key="rp_go")
    if go and st.session_state.rp_address.strip():
        with st.spinner("Reading the records"):
            _start(deps, st.session_state.rp_address, st.session_state.rp_label)
    result = st.session_state.get("rp_result")
    if result is None:
        st.info("Enter a building address to build a report.")
        return
    if "report" in result:
        _show_final(result["report"])
        return
    _show_sections(_sections_so_far(result.get("parts") or {}))
    (interrupt,) = result["__interrupt__"]
    _show_pause(interrupt.value, today)
