"""The landlord report page on fakes (Streamlit AppTest): before the report, at each pause, finished, and stopped early. No graph, no model."""
from streamlit.testing.v1 import AppTest
from test_conditions import case, g
from test_contacts import crow
from test_deeds import drow
from test_identity_graph import FakeIG
from test_profile import BUILDINGS, FakePG
from test_report_full import AllReads, FakeClient, FakeGraph, ReportDeps, identity_rows, resolved
from test_timeline import trow

TODAY = "2026-12-01"


def _page(deps, today):
    from watchline.ui.report_page import render_report_page
    render_report_page(deps, today=today)


def deps(**rows):
    return ReportDeps(FakeClient(resolved()), FakeGraph(), FakePG(buildings=BUILDINGS),
                      AllReads(deeds=[drow()], timeline=[trow()], contacts=[crow()], groups=[g()], cases=[case()]), FakeIG(**identity_rows(**rows)))


def run(address="1 Main St, Manhattan", **rows):
    at = AppTest.from_function(_page, args=(deps(**rows), TODAY), default_timeout=20).run()
    at.text_input(key="rp_address").set_value(address)
    at.text_input(key="rp_label").set_value("demo")
    at.button(key="rp_go").click().run()
    assert not at.exception, at.exception
    return at


def page_text(at):
    return " ".join([*(m.value for m in at.markdown), *(c.value for c in at.caption)])


def test_before_a_report_there_is_a_form_and_a_plain_instruction():
    at = AppTest.from_function(_page, args=(deps(), TODAY)).run()
    assert not at.exception and at.title[0].value == "Landlord report"
    assert [i.value for i in at.info] == ["Enter a building address to build a report."] and not at.get("download_button")
    assert "No text in it is generated" in page_text(at)


def test_a_lead_pauses_the_page_with_the_sections_so_far_and_the_leads_to_decide():
    at = run()
    assert [h.value for h in at.header] == ["About this building", "Who is my landlord?", "How many properties and where?", "Do they hold or sell?"]   # read so far
    assert at.subheader[-1].value == "Your decision on the leads"
    assert at.radio(key="rp_choice_0").options == ["Decide later", "Accept", "Reject"] and at.radio(key="rp_choice_0").value == "Decide later"
    assert at.selectbox(key="rp_role").options == ["researcher", "organizer", "legal staff"]
    t = page_text(at)
    assert "**ACME OWNER** and **ACME OWNR**" in t and "Used:" in t and "Against: The names differ as recorded" in t
    assert ":orange-badge[Lead]" in t and ":gray-badge[Not yet covered]" in t          # a lead is labelled as a lead; a missing step is labelled too
    assert not at.get("download_button") and at.button(key="rp_submit").label == "Save my decisions and finish the report"


def test_accepting_a_lead_finishes_the_report_with_the_decision_the_numbers_and_both_downloads():
    at = run()
    at.radio(key="rp_choice_0").set_value("Accept")
    at.text_input(key="rp_note_0").set_value("same office")
    at.selectbox(key="rp_role").set_value("organizer")
    at.button(key="rp_submit").click().run()
    assert not at.exception, at.exception
    assert "Report for 1 MAIN ST (tax lot 1000010001); landlord record checked: ACME OWNER." in at.success[0].value
    held, decided = at.metric[0], at.metric[1]
    assert (held.label, held.value, decided.label, decided.value) == ("Portfolio as held in the graph", "2 lots", "After your decisions", "3 lots")
    assert "Is there news?" in [h.value for h in at.header] and "Your takeaway" in [h.value for h in at.header]
    assert [d.proto.label for d in at.get("download_button")] == ["Download the report (Markdown)", "Download the decision log (JSON)"] and not at.get("radio")


def test_every_caveat_of_every_section_is_on_the_finished_page_and_in_the_download():
    at = run(lead=False)
    t = page_text(at)
    report = at.session_state["rp_result"]["report"]
    for sec in report["sections"]:
        for c in sec["answer"]["caveats"]:
            assert c["text"] in t, (sec["key"], c["code"])


def test_deciding_later_finishes_with_no_decision_recorded():
    at = run()
    at.button(key="rp_submit").click().run()
    assert not at.exception
    rep = at.session_state["rp_result"]["report"]
    assert rep["decisions"] == [] and rep["checkpoint"]["portfolio_effect"]["as_decided"]["lots"] == 2
    assert at.metric[1].value == "2 lots"


def test_the_decision_is_recorded_with_the_role_the_date_and_the_note():
    at = run()
    at.radio(key="rp_choice_0").set_value("Reject")
    at.text_input(key="rp_note_0").set_value("different office")
    at.button(key="rp_submit").click().run()
    (d,) = at.session_state["rp_result"]["report"]["decisions"]
    assert d == {"linkId": "ACME OWNER|ACME OWNR", "decision": "reject", "decidedBy": "researcher", "decidedAt": TODAY, "note": "different office"}


def test_several_landlord_names_ask_which_one_before_anything_else():
    at = run(covering=(("ACME OWNER", "1000010001"), ("OTHER NAME", "1000010001")), lead=False)
    assert at.selectbox(key="rp_landlord").options == ["ACME OWNER", "OTHER NAME"] and "Which landlord record should the report check?" in [s.value for s in at.subheader]
    at.selectbox(key="rp_landlord").set_value("OTHER NAME")
    at.button(key="rp_pick").click().run()
    assert not at.exception and at.session_state["rp_result"]["report"]["landlord"] == "OTHER NAME"


def test_an_address_that_cannot_be_used_says_why_and_shows_no_sections():
    at = run(address="1 Main St")                                    # no borough
    assert not at.exception and "Give the borough or a ZIP" in at.warning[0].value and not at.header and not at.get("download_button")


def test_a_blank_address_builds_nothing():
    at = AppTest.from_function(_page, args=(deps(), TODAY)).run()
    at.button(key="rp_go").click().run()
    assert not at.exception and at.info and "rp_result" not in at.session_state


def test_the_takeaway_goes_into_the_download_and_is_labelled_as_the_researchers():
    at = run(lead=False)
    at.text_area(key="rp_takeaway").set_value("My reading of the records.").run()
    from watchline.report.export import render_report
    md = render_report(at.session_state["rp_result"]["report"], at.session_state["rp_takeaway"])
    assert "Written by the researcher, not generated:\n\nMy reading of the records." in md


def test_one_lot_and_one_unit_are_not_plural_and_a_note_does_not_end_in_a_double_stop():
    from watchline.identity.section import _state
    from watchline.ui.report_page import _lots, _units
    assert (_lots({"lots": 1}), _lots({"lots": 56}), _units({"units": 1}), _units({"units": 179})) == ("1 lot", "56 lots", "1 residential unit", "179 residential units")
    link = {"state": "accepted", "decision": {"decidedBy": "researcher", "decidedAt": "2026-12-01", "note": "Same office."}}
    assert "note: Same office)." in _state(link)


def test_the_sidebar_pulldown_runs_a_sample_address_like_a_typed_one():
    from watchline.ui.samples import REPORT_SAMPLES
    at = AppTest.from_function(_page, args=(deps(), TODAY), default_timeout=20).run()
    box = at.sidebar.selectbox(key="rp_sample")
    assert list(box.options) == list(REPORT_SAMPLES) and box.value is None and list(REPORT_SAMPLES)[0] == "2141 Washington Avenue, Bronx"
    box.select("2141 Washington Avenue, Bronx").run()
    assert not at.exception, at.exception
    assert at.text_input(key="rp_address").value == "2141 Washington Avenue, Bronx"        # the form shows what was run
    assert at.session_state["rp_graph"] is not None and at.subheader[-1].value == "Your decision on the leads"      # the fake graph resolves any text and finds the lead
    assert at.sidebar.selectbox(key="rp_sample").value is None                              # cleared, so the same sample can be chosen again
    at.sidebar.selectbox(key="rp_sample").select("2141 Washington Avenue, Bronx").run()
    assert not at.exception and at.subheader[-1].value == "Your decision on the leads"


def test_the_sample_addresses_are_listed_with_what_each_shows():
    from watchline.ui.samples import REPORT_SAMPLES
    assert len(REPORT_SAMPLES) == 3 and all(", " in a and d for a, d in REPORT_SAMPLES.items())
    at = AppTest.from_function(_page, args=(deps(), TODAY)).run()
    help_text = at.sidebar.selectbox(key="rp_sample").help
    assert "**2141 Washington Avenue, Bronx**: the lot of the misspelled BADHUMI record" in help_text and "**5413 7 Avenue, Brooklyn**: no landlord record covers the lot" in help_text
