"""Render the structured answer contract in Streamlit. Takes an `Answer`; knows nothing of the agent or the graph.

Bare bones: one generic path for every kind. Caveats are always shown (a line under the facts, the full list in the Evidence
expander), so no kind can drop them.
"""
import streamlit as st

from watchline.agent.answer import Answer, Evidence, EvidenceRef


def _tag(ev: Evidence | EvidenceRef) -> str:
    return f"{ev.section} BIN {ev.bin}" if ev.bin and ev.section in ("buildings", "registrations", "contacts", "violations") else ev.section


def render_answer(answer: Answer, unverified: list[str] = ()) -> None:
    st.markdown(answer.summary)
    if answer.facts:
        for f in answer.facts:
            tags = [_tag(e) for e in f.evidence]
            st.markdown(f"- {f.statement}" + (f"  \n  :gray[{'; '.join(tags)}]" if tags else ""))
            if f.unresolved:
                st.caption("Unverified reference: " + "; ".join(_tag(r) for r in f.unresolved))
    if unverified:
        st.warning(f"These numbers are not in the records and should not be trusted: {', '.join(unverified)}.")
    if answer.caveats:
        st.caption("Caveats apply to this answer. See the evidence below.")
    with st.expander("Evidence: what this answer rests on"):
        evidenced = [(f, e) for f in answer.facts for e in f.evidence]
        if evidenced:
            st.markdown("**Records behind each fact**")
            for f, e in evidenced:
                st.caption(f"{f.statement}  \n{_tag(e)}" + (f" (lot {e.bbl})" if e.bbl else ""))
                st.json(e.data, expanded=False)
        if answer.caveats:
            st.markdown("**Caveats: what the record does and does not establish**")
            for c in answer.caveats:
                st.markdown(f"- {c.text}")
        if answer.sources:
            st.markdown("**Sources**")
            for s in answer.sources:
                st.markdown(f"- {s}")
        if not (evidenced or answer.caveats or answer.sources):
            st.caption("No records were used for this answer.")
