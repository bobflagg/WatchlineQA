"""Bare-bones chat page: `make ui`. Fixtures can be previewed with `?fixtures=1` (no model, graph or sidecar needed).

A sample query picked in the sidebar (first the competency question, then one of its queries) is queued in session state and run on the next pass, the same way as typed input."""
import uuid
from pathlib import Path

import streamlit as st

from watchline.agent.chat import StartupError, ask, connect
from watchline.ui.fixtures import FIXTURES
from watchline.ui.render import render_answer
from watchline.ui.samples import SAMPLE_QUESTIONS

st.set_page_config(page_title="Watchline NYC", layout="wide")

if st.query_params.get("fixtures"):
    for name, answer in FIXTURES.items():
        st.subheader(name)
        render_answer(answer, unverified=["999"] if name == "caveats" else [])
    st.stop()


@st.cache_resource
def _agent():
    from watchline.agent.agent import build_agent, memory_checkpointer
    client, graph, pg, rg, _close = connect()
    return build_agent(client, graph, pg, rg, checkpointer=memory_checkpointer())


if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []          # [(role, text | (Answer, unverified))]

AUTHOR, AUTHOR_EMAIL = "Bob Flagg", "calcworks@gmail.com"
REPO_URL = "https://github.com/bobflagg/WatchlineQA"


def _pick_group():
    """A new competency question was chosen: forget the query chosen under the previous one."""
    st.session_state.sample = None


def _pick_sample():
    """Queue the chosen query, then clear the pulldown so the same query can be picked again."""
    st.session_state.pending = st.session_state.sample
    st.session_state.sample = None


with st.sidebar:
    st.html("<style>.st-key-logo { margin-top: -3.5rem; } .st-key-logo img { border-radius: 12px; }</style>")
    with st.container(key="logo"):
        st.image(str(Path(__file__).parent / "assets" / "logo.png"),
                 alt="Watchline NYC: accountability infrastructure for NYC housing", width="stretch")
    group = st.selectbox("Competency question", list(SAMPLE_QUESTIONS), index=None, key="sample_group",
                         placeholder="Choose a question type", on_change=_pick_group, label_visibility="collapsed")
    st.selectbox("Sample queries", SAMPLE_QUESTIONS.get(group, ()), index=None, key="sample", disabled=group is None,
                 placeholder="Pick a query to run", on_change=_pick_sample, label_visibility="collapsed")
    if st.button("New chat", width="stretch"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.history = []
        st.rerun()
    # Pinned to the bottom of the sidebar. Fixed, so it stays put however tall the pulldowns are; a collapsed sidebar is
    # translated away and takes it along.
    st.html("<style>.st-key-footer { position: fixed; bottom: 1rem; left: 1rem; max-width: 14rem; }</style>")
    with st.container(key="footer"):
        st.caption(f"[{AUTHOR}](mailto:{AUTHOR_EMAIL})  \n[Source on GitHub]({REPO_URL})")

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
