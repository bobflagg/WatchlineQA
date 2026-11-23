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
    assert assemble(model(), [], earlier=[earlier]).caveats == []        # nothing cited, nothing from this turn: no caveats


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
