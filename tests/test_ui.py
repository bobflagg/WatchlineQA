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


def test_contacts_fixture_shows_roles_caveats_and_the_building_tag():
    at = AppTest.from_function(_page)
    at.session_state["name"] = "contacts"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
    for c in FIXTURES["contacts"].caveats:
        assert c.text in text                                  # the agent-is-not-the-owner caveat cannot be dropped
    assert "contacts BIN 3000001" in text
    for f in FIXTURES["contacts"].facts:                       # every person appears with the role recorded
        assert any(role in f.statement for role in ("Agent", "HeadOfficer", "SiteManager"))


def _text(name):
    at = AppTest.from_function(_page)
    at.session_state["name"] = name
    at.run()
    assert not at.exception
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


def test_identity_checkpoint_awaiting_shows_the_lead_the_held_numbers_and_every_caveat():
    text = _text("identity_checkpoint")
    for c in FIXTURES["identity_checkpoint"].caveats:
        assert c.text in text                                   # the lead, shared-address and run-local caveats cannot be dropped
    assert "A lead, awaiting the researcher's decision." in text
    assert "10 lots and 30 residential units" in text and "No decision has been made yet." in text
    assert "links" in text and "portfolio_effect" in text      # the evidence tags name their sections


def test_identity_checkpoint_decided_labels_the_inference_and_shows_the_change():
    text = _text("identity_checkpoint_decided")
    assert "Accepted by the researcher" in text and "the researcher's inference, not a finding in the records" in text
    assert "After the researcher's decisions: 11 lots and 34 residential units" in text
    assert "As held in the graph: 10 lots and 30 residential units" in text              # the held numbers stay visible next to the decided ones
    for c in FIXTURES["identity_checkpoint_decided"].caveats:
        assert c.text in text
    assert "link_is_lead" not in {c.code for c in FIXTURES["identity_checkpoint_decided"].caveats}


def test_violations_fixture_shows_counts_by_class_the_rate_inputs_and_every_caveat():
    text = _text("violations")
    for c in FIXTURES["violations"].caveats:
        assert c.text in text                                   # cited-not-fault and lot-wide cannot be dropped
    assert "4 open violations over 32 residential units, 0.125 per unit" in text and "violations_rate" in text
    assert "severity" not in " ".join(f.statement for f in FIXTURES["violations"].facts).lower()


def test_litigation_fixture_separates_the_finding_from_the_lead_and_keeps_every_caveat():
    text = _text("litigation")
    for c in FIXTURES["litigation"].caveats:
        assert c.text in text
    assert "has a harassment finding, After Trial" in text and "This is a lead." in text and "case_counts" in text


def test_timeline_fixture_shows_counts_caveats_and_the_section_tags():
    at = AppTest.from_function(_page)
    at.session_state["name"] = "timeline"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
    for c in FIXTURES["timeline"].caveats:
        assert c.text in text                                  # the not-a-sale and party-name caveats cannot be dropped
    assert "timeline_counts" in text and "timeline" in text
    assert "total" not in " ".join(f.statement for f in FIXTURES["timeline"].facts).lower()   # counts are never netted into a total


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


def test_sidebar_footer_has_author_email_and_repo_link_with_icons():
    at = AppTest.from_file("../watchline/ui/app.py", default_timeout=10)
    at.run()
    assert not at.exception
    footer = next(h.value for h in at.sidebar.get("html") if "wl-footer" in h.value and "<a " in h.value)
    assert footer.count("<a ") == 2 and footer.count('class="wl-icon ') == 2   # two lines, an icon on each
    assert "<svg" not in footer                                             # st.html's sanitizer strips svg elements
    assert 'href="mailto:calcworks@gmail.com"' in footer and "<span>Bob Flagg</span>" in footer
    assert 'href="https://github.com/bobflagg/WatchlineQA"' in footer and "<span>Source on GitHub</span>" in footer
    assert "Robert" not in footer


def test_footer_icons_are_css_masks_that_survive_the_sanitizer():
    at = AppTest.from_file("../watchline/ui/app.py", default_timeout=10)
    at.run()
    css = next(h.value for h in at.get("html") if ".wl-icon-mail" in h.value)   # style-only html goes to the event container
    assert css.count("data:image/svg+xml,") == 4                            # mask and -webkit-mask, for both icons
    assert "<svg" not in css and "background-color: currentColor" in css      # the data URIs are percent-encoded
