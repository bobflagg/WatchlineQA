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


def test_registration_fixture_shows_its_caveats_and_the_building_tag():
    at = AppTest.from_function(_page)
    at.session_state["name"] = "registration"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
    for c in FIXTURES["registration"].caveats:
        assert c.text in text
    assert "registrations BIN 3000001" in text


def test_a_sample_question_runs_in_the_chat(monkeypatch):
    from types import SimpleNamespace

    from watchline.agent import agent as agent_module
    from watchline.agent import chat
    from watchline.ui.samples import SAMPLE_QUESTIONS
    asked = []
    monkeypatch.setattr(chat, "connect", lambda: (None, None, None, None, lambda: None))
    monkeypatch.setattr(agent_module, "build_agent", lambda *a, **k: object())
    monkeypatch.setattr(chat, "ask", lambda agent, text, config: asked.append(text) or SimpleNamespace(
        structured=None, answer="An answer.", unverified=[]))
    question = SAMPLE_QUESTIONS["Q2: registered owner"][0]
    at = AppTest.from_file("../watchline/ui/app.py", default_timeout=10)
    at.run()
    assert not at.exception and asked == []
    assert at.sidebar.selectbox(key="sample").disabled                 # nothing to pick until a question type is chosen
    at.sidebar.selectbox(key="sample_group").select("Q2: registered owner").run()
    assert not at.exception and asked == []
    assert list(at.sidebar.selectbox(key="sample").options) == list(SAMPLE_QUESTIONS["Q2: registered owner"])
    at.sidebar.selectbox(key="sample").select(question).run()
    assert not at.exception
    assert asked == [question]
    assert [m.value for m in at.chat_message[0].markdown] == [question]
    assert at.sidebar.selectbox(key="sample").value is None       # cleared, so the same query can be chosen again
    assert at.sidebar.selectbox(key="sample_group").value == "Q2: registered owner"
    at.sidebar.selectbox(key="sample").select(question).run()
    assert asked == [question, question]


def test_changing_the_question_type_clears_the_chosen_query(monkeypatch):
    from watchline.ui.samples import SAMPLE_QUESTIONS
    at = AppTest.from_file("../watchline/ui/app.py", default_timeout=10)
    at.run()
    at.sidebar.selectbox(key="sample_group").select("Q1: building profile").run()
    assert list(at.sidebar.selectbox(key="sample").options) == list(SAMPLE_QUESTIONS["Q1: building profile"])
    at.sidebar.selectbox(key="sample_group").select("Q2: registered owner").run()
    assert at.sidebar.selectbox(key="sample").value is None
    assert list(at.sidebar.selectbox(key="sample").options) == list(SAMPLE_QUESTIONS["Q2: registered owner"])
