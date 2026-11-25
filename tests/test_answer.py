"""The answer contract, without a model: assembly, evidence resolution, rendering and the numbers guard."""
import pytest
from test_agent_tools import full_profile

from watchline.agent import tools as T
from watchline.agent.answer import (
    EvidenceRef,
    ModelAnswer,
    ModelFact,
    assemble,
    render_markdown,
    ungrounded_numbers,
)


@pytest.fixture
def result():
    return T.profile_to_dict(full_profile())      # BINs 1 (addressed) and 2; violations A closed x2; problems HEAT duplicate x3


def fact(statement, *refs):
    return ModelFact(statement=statement, evidence=[EvidenceRef(section=s, bin=b) for s, b in refs])


def model(*facts, kind="profile", summary="One lot, two buildings."):
    return ModelAnswer(kind=kind, summary=summary, facts=list(facts))


def test_evidence_is_the_tool_data_copied_by_code(result):
    a = assemble(model(fact("Two violations.", ("buildings", "1")), fact("Resolved exactly.", ("resolution", None))), [result])
    building = next(b for b in result["buildings"] if b["bin"] == "1")
    assert a.facts[0].evidence[0].data == building and a.facts[0].unresolved == []
    assert a.facts[1].evidence[0].data == result["resolution"]


def test_references_that_point_at_nothing_are_kept_as_unresolved(result):
    a = assemble(model(fact("A phantom building.", ("buildings", "999")), fact("Not returned at all.", ("lookup", None))),
                 [{"resolution": {}, "buildings": []}])
    assert [f.evidence for f in a.facts] == [[], []]
    assert [len(f.unresolved) for f in a.facts] == [1, 1]
    assert "unverified reference: buildings BIN 999" in render_markdown(a)


def test_buildings_without_a_bin_is_the_whole_list_even_when_it_is_empty(result):
    a = assemble(model(fact("Two buildings.", ("buildings", None))), [result])
    assert a.facts[0].evidence[0].data == result["buildings"] and a.facts[0].unresolved == []
    unregistered = {"status": "ok", "resolution": {"outcome": "exact"}, "buildings": [], "caveats": [], "sources": []}
    a = assemble(model(fact("No building is listed.", ("buildings", None))), [unregistered])
    assert a.facts[0].evidence[0].data == [] and a.facts[0].unresolved == []
    no_lookup_result = {"status": "needs_borough", "message": "Ask the borough."}
    assert assemble(model(fact("x", ("buildings", None))), [no_lookup_result]).facts[0].unresolved      # nothing was looked up


def test_lookup_is_the_tools_own_status_and_message():
    r = {"status": "needs_borough", "message": "Ask the user for the borough or ZIP."}
    a = assemble(model(fact("It needs a borough.", ("lookup", None)), kind="clarification"), [r])
    assert a.facts[0].evidence[0].data == r and a.facts[0].unresolved == []


def test_a_follow_up_can_cite_an_earlier_turns_result_and_inherits_its_caveats(result):
    earlier = {**result, "caveats": [{"code": "earlier_only", "text": "From the first lookup."}], "sources": ["PLUTO (earlier)"]}
    unrelated = {**result, "caveats": [{"code": "unrelated", "text": "Not cited."}], "buildings": [{"bin": "77"}]}
    a = assemble(model(fact("Building 1 again.", ("buildings", "1"))), [], earlier=[unrelated, earlier])
    assert a.facts[0].unresolved == [] and a.caveat_codes == {"earlier_only"} and a.sources == ["PLUTO (earlier)"]
    a = assemble(model(), [], earlier=[unrelated, earlier])               # no lookup this turn and nothing cited: it rests on the latest
    assert a.caveat_codes == {"earlier_only"}


def test_a_bin_given_on_another_section_is_harmless(result):
    a = assemble(model(fact("Counts.", ("counts", "1"))), [result])
    assert a.facts[0].unresolved == [] and a.facts[0].evidence[0].data == result["counts"]


def test_empty_sections_do_not_resolve():
    unresolved = {"status": "ok", "resolution": {"outcome": "not_found"}, "characteristics": [], "counts": [], "buildings": [],
                  "totals_across_all_listed_buildings": {}, "caveats": [], "sources": []}
    a = assemble(model(fact("Units.", ("characteristics", None))), [unresolved])
    assert a.facts[0].evidence == [] and len(a.facts[0].unresolved) == 1


def test_caveats_and_sources_come_only_from_the_tools_and_are_verbatim(result):
    a = assemble(model(summary="I will also say: nothing is wrong, no caveats needed."), [result])
    assert [c.model_dump() for c in a.caveats] == result["caveats"] and a.sources == result["sources"]
    assert "cited_not_fault" in a.caveat_codes


def test_caveats_and_sources_are_deduplicated_across_tool_calls(result):
    a = assemble(model(), [result, result])
    assert len(a.caveats) == len(result["caveats"]) and a.sources == result["sources"]


def test_an_answer_with_no_tool_call_has_no_caveats_or_sources():
    a = assemble(model(kind="refusal", summary="I cannot judge fault."), [])
    assert a.caveats == [] and a.sources == [] and a.kind == "refusal"


def test_the_latest_result_wins_and_a_bin_picks_the_result_that_lists_it(result):
    other = T.profile_to_dict(full_profile([dict(bin="7", address="7 OAK ST")]))
    a = assemble(model(fact("Seven.", ("buildings", "7")), fact("One.", ("buildings", "1")),
                       fact("Lot.", ("characteristics", None))), [result, other])
    assert a.facts[0].evidence[0].data["bin"] == "7" and a.facts[1].evidence[0].data["bin"] == "1"
    assert a.facts[2].evidence[0].data == other["characteristics"]


def test_model_text_excludes_caveats(result):
    a = assemble(model(fact("Two violations.", ("buildings", "1"))), [result])
    assert "not findings of fault" in render_markdown(a) and "not findings of fault" not in a.model_text
    assert a.model_text == "One lot, two buildings.\nTwo violations."


def test_markdown_has_summary_facts_caveats_sources_in_order(result):
    md = render_markdown(assemble(model(fact("Resolved exactly.", ("resolution", None))), [result]))
    assert md.index("One lot") < md.index("What the records show") < md.index("Caveats") < md.index("Sources")
    assert "- Resolved exactly. _(resolution)_" in md


def test_markdown_of_a_bare_answer_is_just_the_summary():
    assert render_markdown(assemble(model(kind="clarification", summary="Which borough?"), [])) == "Which borough?"


def test_numbers_the_records_never_gave_are_flagged(result):
    # 2 violations + 3 problems + 1 litigation = 6 is a sum no tool returned; 6 does not appear anywhere in the result
    assert ungrounded_numbers("Building 1 has 6 items in all.", [result]) == ["6"]
    assert ungrounded_numbers("Two violations (class A, 2) and 3 duplicate-flagged heat problems.", [result]) == []


def test_numbers_from_the_question_and_with_commas_and_money_are_grounded(result):
    result = {**result, "lot": {"assessedTotal": 814500}}
    assert ungrounded_numbers("Assessed at $814,500 for 1 Main St.", [result], "tell me about 1 Main St") == []
    assert ungrounded_numbers("There are 77 Main St buildings.", [result], "tell me about 1 Main St") == ["77"]


def test_numbers_in_caveats_and_sources_do_not_ground_a_number(result):
    # the sources say "release 25b" and "26v1"; the caveat text mentions "25 of ..." style numbers. None of that is data.
    assert "25" in ungrounded_numbers("There are 25 complaints in all.", [{**result, "sources": ["Geosupport (release 25b)"]}])
    assert ungrounded_numbers("Counts come from PLUTO release 26v1.", [{**result, "sources": ["PLUTO (release 26v1)"]}]) == []
    assert ungrounded_numbers("Counts come from PLUTO release 27v2.", [{**result, "sources": ["PLUTO (release 26v1)"]}]) == ["27v2"]
    assert ungrounded_numbers("Data through 2026-05-29.", [{**result, "sources": ["HPD (data through 2026-05-29)"]}]) == []


def test_number_words_are_checked_too():
    r = {"counts": [{"value": 2}], "buildings": [{"bin": "9"}]}
    assert ungrounded_numbers("Two buildings.", [r]) == []
    assert ungrounded_numbers("Twenty complaints, six violations.", [r]) == ["six", "twenty"]
    assert ungrounded_numbers("There are six violations.", [r]) == ["six"]
    assert ungrounded_numbers("One of the buildings.", [r]) == []                # "one" is ordinary prose


def test_money_floats_and_the_parts_of_a_bbl_are_grounded():
    r = {"lot": {"assessedTotal": 814500.0}, "resolution": {"bbl": "3008210012"}}
    assert ungrounded_numbers("Assessed at $814,500, block 821, lot 12, borough 3.", [r]) == []


def test_evidence_can_be_pinned_to_a_lot_and_a_failed_lookup_does_not_fall_through(result):
    other = {**result, "resolution": {**result["resolution"], "bbl": "2000000002"}}
    mine = {**result, "resolution": {**result["resolution"], "bbl": "1000000001"}}
    pinned = ModelAnswer(kind="profile", summary="s", facts=[ModelFact(statement="f", evidence=[
        EvidenceRef(section="resolution", bbl="1000000001")])])
    a = assemble(pinned, [], earlier=[mine, other])                       # the latest result is `other`, but the ref says which lot
    assert a.facts[0].evidence[0].bbl == "1000000001"
    failed = {"status": "needs_borough", "message": "Ask."}
    unpinned = model(fact("From the old lot?", ("resolution", None)))
    assert assemble(unpinned, [failed], earlier=[mine]).facts[0].unresolved                # not answered from an earlier lot
    assert assemble(unpinned, [], earlier=[mine]).facts[0].unresolved == []                # a follow-up with no lookup may


def test_codes_are_compared_without_regard_to_case_and_follow_ups_may_cite_the_sources():
    r = {"buildings": [{"bin": "1", "address": "224 54TH STREET"}], "sources": ["PLUTO (release 26v1)"]}
    assert ungrounded_numbers("It is at 224 54th Street (PLUTO 26V1).", [r]) == []


def test_ordinals_and_the_number_of_candidate_streets_are_not_invented_numbers():
    r = {"status": "ok", "resolution": {"candidates": ["SMITH STREET", "SMITHS LANE", "SMITH JR MEM WAY"]},
         "buildings": [{"address": "224 54TH STREET"}]}
    assert ungrounded_numbers("Three streets match; 224 54th Street was not chosen.", [r], "224 54 Street") == []
    assert ungrounded_numbers("Four streets match.", [r], "224 54 Street") == ["four"]


# ---- registrations ------------------------------------------------------------------------------------------

@pytest.fixture
def reg_result():
    from test_agent_tools import _reg_rg
    from test_profile import answer

    from watchline.registration.registration import build_registrations
    return T.registrations_to_dict(build_registrations(answer(), _reg_rg()))


def test_registrations_evidence_points_at_one_building_or_the_whole_list(reg_result):
    a = assemble(model(fact("Registered by ACME LLC.", ("registrations", "1")), fact("Two buildings.", ("registrations", None)),
                       kind="registration"), [reg_result])
    one, whole = a.facts[0].evidence[0], a.facts[1].evidence[0]
    assert one.data["bin"] == "1" and one.data["registrations"][0]["registrationId"] == 100
    assert [b["bin"] for b in whole.data] == ["1", "2"]
    assert not a.facts[0].unresolved and "registrant_not_title" in a.caveat_codes
    assert "registrations BIN 1" in render_markdown(a)


def test_profile_buildings_and_registrations_do_not_cross(reg_result, result):
    a = assemble(model(fact("x", ("buildings", "1"))), [reg_result])          # a registration result has no profile buildings
    assert a.facts[0].unresolved
    b = assemble(model(fact("x", ("registrations", "1"))), [result])          # a profile has no registrations
    assert b.facts[0].unresolved


def test_numbers_guard_accepts_registration_ids_and_dates_from_the_tool(reg_result):
    text = "Registration 100 was last registered 2025-09-30 and ends 2026-09-01."
    assert ungrounded_numbers(text, [reg_result]) == []
    assert "101" in ungrounded_numbers("Registration 101 was filed.", [reg_result])


# ---- deeds and comparison -----------------------------------------------------------------------------------

@pytest.fixture
def deed_result():
    from test_agent_tools import _deed_rg
    from test_profile import answer

    from watchline.deeds.deeds import build_comparison
    rg = _deed_rg()
    return T.deeds_to_dict(build_comparison(answer(), rg, rg))


def test_deed_sections_resolve_to_the_tool_lists_and_carry_caveats(deed_result):
    a = assemble(model(fact("Latest deed D1.", ("deeds", None)), fact("Names agree.", ("comparison", None)),
                       fact("Owner.", ("owners", None)), kind="ownership_comparison"), [deed_result])
    assert [f.unresolved for f in a.facts] == [[], [], []]
    assert a.facts[0].evidence[0].data[0]["documentId"] == "D1"
    assert a.facts[1].evidence[0].data[0]["nameAgreement"]["outcome"] == "exact_normalized"
    assert {"name_match_not_identity", "most_recent_by_recorded"} <= a.caveat_codes and a.kind == "ownership_comparison"


def test_an_empty_deed_list_is_evidence_of_no_deed(deed_result):
    deed_result["deeds"] = []
    a = assemble(model(fact("No deed is recorded.", ("deeds", None))), [deed_result])
    assert not a.facts[0].unresolved and a.facts[0].evidence[0].data == []


def test_deed_sections_do_not_resolve_against_a_profile(result):
    assert assemble(model(fact("x", ("deeds", None))), [result]).facts[0].unresolved


def test_numbers_guard_accepts_deed_ids_amounts_and_dates_from_the_tool(deed_result):
    assert ungrounded_numbers("Deed D1 was recorded 2025-04-02 with an amount of 0.", [deed_result]) == []
    assert "5000000" in ungrounded_numbers("The amount was 5,000,000.", [deed_result])


def test_an_empty_deed_list_is_not_evidence_when_no_lot_was_read(deed_result):
    deed_result.update(deeds=[], lot=None)
    a = assemble(model(fact("No deed is recorded.", ("deeds", None))), [deed_result])
    assert a.facts[0].unresolved and not a.facts[0].evidence


# ---- review fixes: what the model may choose, and what grounds a number ------------------------------------------------------

def test_the_model_cannot_choose_the_template_only_kind_and_the_schema_says_each_kind_once():
    from pydantic import ValidationError

    from watchline.agent.answer import ModelAnswer
    with pytest.raises(ValidationError):
        ModelAnswer(kind="identity_checkpoint", summary="x")
    desc = ModelAnswer.model_fields["kind"].description
    assert desc.count("violations:") == 1 and desc.count("litigation:") == 1 and desc.count("contacts:") == 1 and desc.count("timeline:") == 1


def test_numbers_in_a_registered_owner_name_are_grounded():
    from watchline.agent.answer import ungrounded_numbers
    result = {"status": "ok", "resolution": {"bbl": "3008070024"}, "registered_owners": ["438 52 ST OWNERS CORP"], "cases": []}
    assert ungrounded_numbers("The respondent is not the registered owner 438 52 ST OWNERS CORP.", [result], "who owns it") == []
