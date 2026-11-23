import pytest
from streamlit.testing.v1 import AppTest

from watchline.ui.fixtures import FIXTURES


def _page():
    import streamlit as st

    from watchline.ui.fixtures import FIXTURES
    from watchline.ui.render import render_answer
    render_answer(FIXTURES[st.session_state.name])


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_renders(name):
    at = AppTest.from_function(_page)
    at.session_state["name"] = name
    at.run()
    assert not at.exception
    assert FIXTURES[name].summary in at.markdown[0].value


def test_caveats_never_dropped():
    at = AppTest.from_function(_page)
    at.session_state["name"] = "profile"
    at.run()
    text = " ".join(m.value for m in at.markdown)
    for c in FIXTURES["profile"].caveats:
        assert c.text in text
    assert any("Caveats apply" in c.value for c in at.caption)
