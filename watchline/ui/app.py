"""The Watchline app: `make ui`. Two pages, the chat and the landlord report, under one navigation. Fixtures can be previewed with `?fixtures=1`
(no model, graph or sidecar needed).

The chat page needs the model key; the report page does not. A sample query picked in the chat sidebar is queued in session state and run on the next pass,
the same way as typed input."""
import streamlit as st

from watchline.ui.fixtures import FIXTURES
from watchline.ui.render import render_answer

st.set_page_config(page_title="Watchline NYC", layout="wide")

if st.query_params.get("fixtures"):
    for name, answer in FIXTURES.items():
        st.subheader(name)
        render_answer(answer, unverified=["999"] if name == "caveats" else [])
    st.stop()

st.navigation([
    st.Page("app_pages/chat.py", title="Chat", icon=":material/chat:", default=True),
    st.Page("app_pages/report.py", title="Landlord report", icon=":material/description:", url_path="report"),
]).run()
