"""The landlord report page on the real graph: `make report-ui`. Needs Neo4j and the Geosupport sidecar; no model, no API key."""
import streamlit as st

from watchline.agent.chat import StartupError, connect_all
from watchline.report.graph import ReportDeps
from watchline.ui.report_page import render_report_page

st.set_page_config(page_title="Landlord report · Watchline NYC", layout="wide")


@st.cache_resource
def _deps() -> ReportDeps:
    client, graph, pg, rg, ig, _close = connect_all()
    return ReportDeps(client, graph, pg, rg, ig)


try:
    deps = _deps()
except StartupError as exc:
    st.error(f"Cannot start: {exc}")
    st.stop()
render_report_page(deps)
