"""The chat page (one of the app's pages; see `watchline/ui/app.py`).

A sample query picked in the sidebar (first the competency question, then one of its queries) is queued in session state and run on the next pass, the same way as typed input."""
import uuid

import streamlit as st

from watchline.agent.chat import StartupError, ask, connect
from watchline.ui.render import render_answer
from watchline.ui.samples import SAMPLE_QUESTIONS


@st.cache_resource
def _agent():
    from watchline.agent.agent import build_agent, memory_checkpointer
    client, graph, pg, rg, _close = connect()
    return build_agent(client, graph, pg, rg, checkpointer=memory_checkpointer())


if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []          # [(role, text | (Answer, unverified))]

def _pick_group():
    """A new competency question was chosen: forget the query chosen under the previous one."""
    st.session_state.sample = None


def _pick_sample():
    """Queue the chosen query, then clear the pulldown so the same query can be picked again."""
    st.session_state.pending = st.session_state.sample
    st.session_state.sample = None


with st.sidebar:
    group = st.selectbox("Competency question", list(SAMPLE_QUESTIONS), index=None, key="sample_group",
                         placeholder="Choose a question type", on_change=_pick_group, label_visibility="collapsed")
    st.selectbox("Sample queries", SAMPLE_QUESTIONS.get(group, ()), index=None, key="sample", disabled=group is None,
                 placeholder="Pick a query to run", on_change=_pick_sample, label_visibility="collapsed")
    if st.button("New chat", width="stretch"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.history = []
        st.rerun()

for role, item in st.session_state.history:
    with st.chat_message(role):
        if isinstance(item, str):
            st.markdown(item)
        else:
            render_answer(*item)

typed = st.chat_input("Ask about a New York City address")
if prompt := st.session_state.pop("pending", None) or typed:
    st.session_state.history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            agent = _agent()
            with st.spinner("Looking up the records"):
                turn = ask(agent, prompt, {"configurable": {"thread_id": st.session_state.thread_id}})
        except StartupError as exc:
            item = f"Cannot start: {exc}"
        except Exception as exc:    # noqa: BLE001  an API or graph failure ends the turn, not the page
            item = f"That question failed: {type(exc).__name__}. Nothing was answered; try again."
        else:
            if turn.structured is None:
                item = turn.answer + "\n\n_The model did not return a structured answer, so no caveats or sources are attached._"
            else:
                item = (turn.structured, turn.unverified)
        if isinstance(item, str):
            st.markdown(item)
        else:
            render_answer(*item)
    st.session_state.history.append(("assistant", item))
