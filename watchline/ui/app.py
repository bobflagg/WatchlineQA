"""The Watchline app: `make ui`. Two pages, the chat and the landlord report. The sidebar (logo, links to the pages below it, author footer) is drawn here, so it
stays when the page changes; each page adds its own widgets under it. Fixtures can be previewed with `?fixtures=1` (no model, graph or sidecar needed).

The chat page needs the model key; the report page does not. A sample query picked in the chat sidebar is queued in session state and run on the next pass,
the same way as typed input."""
import streamlit as st

from watchline.ui.fixtures import FIXTURES
from watchline.ui.render import render_answer
from watchline.ui.sidebar import render_sidebar

st.set_page_config(page_title="Watchline NYC", layout="wide")

if st.query_params.get("fixtures"):
    for name, answer in FIXTURES.items():
        st.subheader(name)
        render_answer(answer, unverified=["999"] if name == "caveats" else [])
    st.stop()

chat = st.Page("app_pages/chat.py", title="Chat", icon=":material/chat:", default=True)
report = st.Page("app_pages/report.py", title="Landlord report", icon=":material/description:", url_path="report")
page = st.navigation([chat, report], position="hidden")      # the links are drawn below the logo by render_sidebar
with st.sidebar:
    render_sidebar([(chat, "Chat", ":material/chat:"), (report, "Landlord report", ":material/description:")])
page.run()
