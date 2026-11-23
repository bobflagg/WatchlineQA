"""Bare-bones chat page: `make ui`. Fixtures can be previewed with `?fixtures=1` (no model, graph or sidecar needed)."""
import uuid
from pathlib import Path

import streamlit as st

from watchline.agent.chat import StartupError, ask, connect
from watchline.ui.fixtures import FIXTURES
from watchline.ui.render import render_answer

st.set_page_config(page_title="Watchline NYC", layout="wide")

if st.query_params.get("fixtures"):
    for name, answer in FIXTURES.items():
        st.subheader(name)
        render_answer(answer, unverified=["999"] if name == "caveats" else [])
    st.stop()


@st.cache_resource
def _agent():
    from watchline.agent.agent import build_agent, memory_checkpointer
    client, graph, pg, _close = connect()
    return build_agent(client, graph, pg, checkpointer=memory_checkpointer())


if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.history = []          # [(role, text | (Answer, unverified))]

with st.sidebar:
    st.html("<style>.st-key-logo { margin-top: -3.5rem; } .st-key-logo img { border-radius: 12px; }</style>")
    with st.container(key="logo"):
        st.image(str(Path(__file__).parent / "assets" / "logo.png"),
                 alt="Watchline NYC: accountability infrastructure for NYC housing", width="stretch")
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

if prompt := st.chat_input("Ask about a New York City address"):
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
