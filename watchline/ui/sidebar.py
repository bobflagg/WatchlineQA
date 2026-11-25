"""What every page of the app shares in the sidebar: the logo, the links to the pages (below the logo), and the author footer pinned to the bottom.

It is drawn once, by the entry script (`app.py`), before the page runs, so it stays when the page changes. A page adds its own widgets below it.
"""
from pathlib import Path
from urllib.parse import quote

import streamlit as st

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


LOGO_CSS = "<style>.st-key-logo { margin-top: -3.5rem; } .st-key-logo img { border-radius: 12px; }</style>"      # tucked up under the top edge


def render_sidebar(pages: list[tuple[st.Page, str, str]]) -> None:
    """The logo, then one link per page (page, label, icon), then the footer. Call it inside `with st.sidebar:`."""
    st.html(LOGO_CSS)
    with st.container(key="logo"):
        st.image(str(Path(__file__).parent / "assets" / "logo.png"), alt="Watchline NYC: accountability infrastructure for NYC housing", width="stretch")
    for page, label, icon in pages:
        st.page_link(page, label=label, icon=icon)
    # Pinned to the bottom of the sidebar. Fixed, so it stays put however tall the pulldowns are; a collapsed sidebar is
    # translated away and takes it along. Icons are CSS masks (see above).
    st.html(FOOTER_CSS)
    with st.container(key="footer"):
        st.html(footer_html())
