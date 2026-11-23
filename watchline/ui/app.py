"""Bare-bones chat page: `make ui`. Fixtures can be previewed with `?fixtures=1` (no model, graph or sidecar needed).

A sample query picked in the sidebar (first the competency question, then one of its queries) is queued in session state and run on the next pass, the same way as typed input."""
import uuid
from pathlib import Path
from urllib.parse import quote

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


# st.html sanitizes with DOMPurify's HTML-only profile, which strips <svg>. So each icon is an empty <span> painted through a CSS mask
# made from a data-URI SVG: it takes the text color (currentColor) and turns gold on hover.
_MAIL_PATH = ("M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z")
_GITHUB_PATH = ("M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13"
                "-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15"
                "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15"
                " 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z")


def _mask(path: str, size: int) -> str:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"><path d="{path}"/></svg>'
    return f'url("data:image/svg+xml,{quote(svg)}") center / contain no-repeat'


FOOTER_CSS = f"""<style>
.st-key-footer {{ position: fixed; bottom: 1rem; left: 1rem; max-width: 14rem; }}
.wl-footer a {{ display: flex; align-items: center; gap: 0.5rem; padding: 0.15rem 0; font-size: 0.85rem; color: inherit;
               text-decoration: none; opacity: 0.85; }}
.wl-footer a:hover {{ color: #d4a017; opacity: 1; }}
.wl-icon {{ width: 1rem; height: 1rem; flex: none; background-color: currentColor; }}
.wl-icon-mail {{ -webkit-mask: {_mask(_MAIL_PATH, 24)}; mask: {_mask(_MAIL_PATH, 24)}; }}
.wl-icon-github {{ -webkit-mask: {_mask(_GITHUB_PATH, 16)}; mask: {_mask(_GITHUB_PATH, 16)}; }}
</style>"""


def footer_html() -> str:
    """Two lines: the author (a mailto link) and the repository, each with an icon."""
    return (f'<div class="wl-footer"><a href="mailto:{AUTHOR_EMAIL}"><span class="wl-icon wl-icon-mail"></span><span>{AUTHOR}</span></a>'
            f'<a href="{REPO_URL}" target="_blank" rel="noopener noreferrer"><span class="wl-icon wl-icon-github"></span><span>Source on GitHub</span></a></div>')


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
    # translated away and takes it along. Icons are CSS masks (see below).
    st.html(FOOTER_CSS)
    with st.container(key="footer"):
        st.html(footer_html())

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
