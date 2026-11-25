"""Report sections (PESP steps 2 to 4 and 8) as templated Answers. Fake rows through the real builders and the tool views; no graph, no model."""
import pytest
from test_agent_tools import _deed_rg
from test_conditions import FakeCG, case, g
from test_contacts import FakeCG as ContactCG
from test_contacts import crow
from test_deeds import drow
from test_profile import BUILDINGS, LOT, FakePG, answer
from test_registration import FakeRG, owner, row
from test_timeline import FakeTG, trow

from watchline.agent import tools as T
from watchline.conditions.conditions import build_litigation, build_violations
from watchline.contacts.contacts import build_contacts
from watchline.deeds.deeds import build_comparison
from watchline.deeds.timeline import build_timeline
from watchline.profile.profile import build_profile
from watchline.registration.registration import build_registrations
from watchline.report import sections as S


def codes(a):
    return {c.code for c in a.caveats}


def text(a):
    return " ".join([a.summary, *(f.statement for f in a.facts)])


# ---- step 2 ---------------------------------------------------------------------------------------------------------------

def facts_view(**kw):
    return T.profile_to_dict(build_profile(answer(), FakePG(buildings=BUILDINGS, **kw)))


def test_building_facts_keep_lot_wide_values_apart_and_name_both_building_counts():
    a = S.building_facts(facts_view())
    t = text(a)
    assert a.kind == "profile" and "tax lot 1000010001" in a.summary and "24 residential units (a lot-wide figure)" in a.summary
    assert "built 1931, building class C1, with 24 residential units and an assessed total of $1,000" in t and "belong to the lot, not to any one building" in t
    assert "HPD registrations list 2 buildings; PLUTO counts 2" in t and "1 MAIN ST (BIN 1) (the address typed); 3 MAIN ST (BIN 2)" in t
    assert "The address matched exactly to 1 Main St, tax lot 1000010001." in t
    assert {"cited_not_fault", "lot_wide"} <= codes(a) and any("PLUTO" in s for s in a.sources)
    assert all(f.evidence for f in a.facts) and [f.evidence[0].section for f in a.facts][:3] == ["resolution", "characteristics", "counts"]


def test_building_facts_do_not_repeat_the_conditions_counts():
    t = text(S.building_facts(facts_view(violations=[dict(bin="1", violationClass="A", status="Open", n=9)])))
    assert "violation" not in t.lower().replace("violations, complaint", "")        # those belong to step 8


def test_an_unresolved_or_missing_lot_says_why_and_reads_nothing():
    v = T.profile_to_dict(build_profile(answer(in_graph=False), FakePG()))
    a = S.building_facts(v)
    assert a.kind == "not_found" and "no such lot" in a.summary and not a.facts and "not_in_graph" in codes(a)
    assert S.building_facts({"status": "error", "lot": None, "caveats": [], "sources": []}).kind == "error"


# ---- step 3 ---------------------------------------------------------------------------------------------------------------

def owner_views(contacts=(), owners=None, rows=None):
    reg = T.registrations_to_dict(build_registrations(answer(), FakeRG(rows=[row()] if rows is None else rows, owners=[owner()] if owners is None else owners)))
    con = T.contacts_to_dict(build_contacts(answer(), ContactCG(contacts, rows=[row()] if rows is None else rows)))
    return reg, con


def test_the_registered_owner_and_every_contact_with_its_role():
    reg, con = owner_views([crow(role="Agent", name="JAY WONG"), crow(role="HeadOfficer", name="BAOZHEN CHEN", title="PRESIDENT")])
    a = S.owner_and_contacts(reg, con)
    t = text(a)
    assert a.kind == "registration" and "ACME LLC (CorporateOwner)" in t and "registration 100 (last registered 2025-09-30, registration ending 2026-09-01)" in t
    assert "lists JAY WONG as Agent, business address 746 61ST STREET, 11220." in t
    assert "lists BAOZHEN CHEN as HeadOfficer (title PRESIDENT)" in t
    assert "not who holds title" in a.summary and {"registrant_not_title", "role_as_recorded", "agent_not_owner"} <= codes(a)
    assert {f.evidence[0].section for f in a.facts} == {"registrations", "contacts"}


def test_no_owner_contact_and_no_registration_are_not_read_as_no_owner():
    reg, con = owner_views(owners=[], rows=[dict(bin="1", address="1 MAIN ST", registrationId=None, lastRegistered=None, registrationEnd=None)])
    a = S.owner_and_contacts(reg, con)
    assert "records no registered owner contact" in a.summary and "says nothing about who owns them" in a.summary
    assert any("has no HPD registration in the data" in f.statement for f in a.facts)


def test_many_buildings_and_contacts_are_counted_not_dumped():
    rows = [row(bin_=str(i), rid=100 + i, address=f"{i} MAIN ST") for i in range(S.MAX_BUILDINGS_SHOWN + 3)]
    contacts = [dict(crow(name=f"P{n}"), registrationId=100) for n in range(S.MAX_CONTACTS_SHOWN + 2)]
    reg, con = owner_views(contacts, rows=rows)
    a = S.owner_and_contacts(reg, con)
    t = text(a)
    assert "3 more buildings are listed" in t and "2 more contacts are recorded on registration 100" in t and "11 MAIN ST" not in t


# ---- step 4 ---------------------------------------------------------------------------------------------------------------

def deed_views(deeds, owners=None, rg_deeds=None):
    tl = T.timeline_to_dict(build_timeline(answer(), FakeTG(deeds)))
    rg = _deed_rg(deed_rows=[drow()] if rg_deeds is None else rg_deeds, owners=owners)
    return tl, T.deeds_to_dict(build_comparison(answer(), rg, rg))


def test_deed_history_counts_deeds_never_calls_zero_a_sale_and_compares_the_latest_as_a_lead():
    tl, cmp = deed_views([trow("D1", rec="2025-04-02", amount=0, grantors=("5413 PLAZA LLC",), grantees=("5413 PLAZA LLC",)),
                          trow("D2", rec="2021-02-26", amount=5000000, grantors=("A SELLER",), grantees=("5413 PLAZA LLC",), other=3)])
    a = S.deed_history(tl, cmp)
    t = text(a)
    assert a.kind == "timeline" and "2 deeds recorded on the lot, the latest on 2025-04-02" in a.summary and "A deed records a transfer of title, not a sale" in a.summary
    assert "Deed D1, recorded 2025-04-02 (DEED), an amount of 0, which is not a sale; from 5413 PLAZA LLC to 5413 PLAZA LLC." in t
    assert "an amount of 5,000,000 recorded; from A SELLER to 5413 PLAZA LLC; it also names 3 other lots." in t
    assert "never proof that two records are one party" in t and "deed_not_sale" in codes(a) and "name_match_not_identity" in codes(a)
    assert "sold" not in t.lower() and "was a sale" not in t.lower()


def test_a_correction_deed_and_a_missing_amount_are_worded_as_what_they_are():
    tl, _ = deed_views([trow("C1", typ="CORRD", amount=10), trow("N1", amount=None)])
    t = text(S.deed_history(tl))
    assert "10 (a correction or confirmatory deed, not a sale)" in t and "no amount recorded" in t


def test_no_deed_says_so_and_a_long_history_is_listed_newest_first_with_a_count_of_the_rest():
    tl, _ = deed_views([])
    a = S.deed_history(tl)
    assert "does not mean the lot never changed hands" in a.summary and not a.facts
    tl, _ = deed_views([trow(f"D{n}", rec=f"20{20 - n:02d}-01-01") for n in range(S.MAX_ITEMS_SHOWN + 2)])
    t = text(S.deed_history(tl))
    assert "2 older deeds are listed in the evidence." in t and t.index("D0") < t.index("D1")


def test_a_latest_deed_with_no_registered_owner_is_not_compared():
    tl, cmp = deed_views([trow("D1")], owners=[])
    assert "could not be compared with a registered owner" in text(S.deed_history(tl, cmp))


# ---- step 8 ---------------------------------------------------------------------------------------------------------------

def vio(groups, units=32):
    return T.violations_to_dict(build_violations(answer(), FakeCG(lot=dict(LOT, unitsRes=units), buildings=[BUILDINGS[0]], groups=groups)))


def test_violations_by_class_with_the_rate_and_its_inputs_and_never_one_score():
    a = S.violations_section(vio([g("1", "B", "Open", 2, "2023-03-25"), g("1", "C", "Open", 2, "2024-02-01"), g("1", "A", "Close", 1, "2019-01-01")]))
    t = text(a)
    assert "4 open violations on the lot's buildings. Violations are what an inspector cited, not findings of fault" in a.summary
    assert "open violations class B: 2 and class C: 2; the oldest open inspection was on 2023-03-25; closed violations class A: 1." in t
    assert "0.125 (4 open over 32 units, pooled across the lot's buildings); by class: class B 0.062 and class C 0.062. The units are a lot-wide figure." in t
    assert {"cited_not_fault", "open_at_snapshot", "lot_wide"} <= codes(a) and "severity" not in t.lower()


def test_a_missing_unit_count_gives_no_rate_and_no_violations_is_not_a_clean_record():
    t = text(S.violations_section(vio([g("1", "A", "Open", 1)], units=0)))
    assert "The rate per unit is unavailable" in t and "Open violations counted: 1" in t
    a = S.violations_section(vio([]))
    assert "not a statement that conditions are good" in a.summary and "has no violation recorded" in text(a)


def lit(cases, owners=("ACME LLC",)):
    return T.litigation_to_dict(build_litigation(answer(), FakeCG(cases=cases, owners=[dict(name=o) for o in owners])))


def test_a_harassment_finding_is_on_the_case_at_the_building_and_a_respondent_match_is_a_lead():
    a = S.litigation_section(lit([case(1, finding="After Trial", findingDate="2016-07-25", penalty=5200, resp="X PERSON", keys=("X PERSON",)),
                                  case(2, resp="ACME LLC,JOHN DOE", keys=("ACME LLC", "JOHN DOE")), case(3, finding="No Harassment", resp=None, keys=None)]))
    t = text(a)
    assert "1 case carries a recorded harassment finding (After Inquest or After Trial)." in a.summary
    assert "has a recorded harassment finding, After Trial, dated 2016-07-25, with a penalty of 5,200. The finding is recorded on this case at the building." in t
    assert "Respondent as recorded: X PERSON. No part of it matches a registered owner name." in t
    assert "ACME LLC matches a registered owner name as written; that is a lead, not proof of the same party." in t
    assert "It cannot be compared with an owner name." in t and "harassment finding recorded." in t
    assert "owner was found" not in t and {"harassment_finding_definition", "case_not_finding", "name_match_not_identity"} <= codes(a)


def test_no_cases_and_more_cases_than_listed():
    assert "does not mean none was ever brought" in S.litigation_section(lit([])).summary
    d = lit([case(i) for i in range(1, 4)])
    d["cases"] = d["cases"][:1]
    assert "2 more cases are counted above and not listed." in text(S.litigation_section(d))


def test_not_covered_says_what_is_missing_and_never_looks_silent():
    a = S.not_covered("Entity research", "The DOS record for the owner entity is not in this report yet.")
    assert a.kind == "not_covered" and a.summary.startswith("Not yet covered: Entity research.") and "not_covered" in codes(a) and not a.facts


@pytest.mark.parametrize("fn, view", [(S.building_facts, lambda: facts_view()), (S.violations_section, lambda: vio([g()])), (S.litigation_section, lambda: lit([case()]))])
def test_sections_are_deterministic(fn, view):
    assert fn(view()) == fn(view())
