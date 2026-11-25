"""Q4 contacts: section function, tool view and contract wiring. No model, no graph."""
import pytest
from test_agent_tools import FakeClient, FakeGraph, resolved
from test_profile import answer
from test_registration import FakeRG, row

from watchline.agent import tools as T
from watchline.agent.answer import EvidenceRef, ModelAnswer, ModelFact, assemble
from watchline.contacts import contacts as C
from watchline.contacts.contacts import build_contacts
from watchline.profile import profile as P


class FakeCG(FakeRG):
    def __init__(self, contacts=(), **kw):
        super().__init__(**kw)
        self._contacts = list(contacts)

    def contacts(self, bbl): return self._contacts


def crow(rid=100, role="Agent", name="JAY WONG", title=None, addr="746 61ST STREET", zip_="11220", l2=None):
    return dict(registrationId=rid, role=role, name=name, title=title, mailingAddress=addr, addressLine2=l2, zip=zip_)


def run(contacts, rows=None, **kw):
    return build_contacts(answer(**kw), FakeCG(contacts, rows=[row()] if rows is None else rows))


def codes(c):
    return {x.code for x in c.caveats}


def roles(c):
    return [(x.role, x.name, x.title) for b in c.buildings for g in b.registrations for x in g.contacts]


# ---- content ---------------------------------------------------------------------------------------------------------

def test_every_role_is_listed_with_its_title_and_address_and_none_is_chosen():
    c = run([crow(role="Agent"), crow(role="CorporateOwner", name="5413 PLAZA LLC"), crow(role="HeadOfficer", name="BAOZHEN CHEN", title="PRESIDENT"),
             crow(role="SiteManager", addr=None, zip_=None)])
    assert roles(c) == [("Agent", "JAY WONG", None), ("CorporateOwner", "5413 PLAZA LLC", None),
                        ("HeadOfficer", "BAOZHEN CHEN", "PRESIDENT"), ("SiteManager", "JAY WONG", None)]
    assert c.buildings[0].registrations[0].contacts[3].mailingAddress is None


def test_same_name_in_two_roles_is_two_contacts_and_exact_duplicates_collapse():
    c = run([crow(role="Agent"), crow(role="SiteManager", addr=None, zip_=None), crow(role="Agent")])
    assert [r for r, _, _ in roles(c)] == ["Agent", "SiteManager"]


def test_caveats_for_roles_agents_and_shared_address():
    c = run([crow(role="Agent"), crow(role="HeadOfficer", name="BAOZHEN CHEN", title="PRESIDENT")])
    assert {"role_as_recorded", "agent_not_owner", "shared_address_not_evidence", "registrant_not_title", "registration_period"} <= codes(c)
    assert "owner_not_other_roles" not in codes(c) and "no_owner_contact" not in codes(c)       # Q2's owner-only caveats do not apply


def test_only_owner_contacts_have_no_agent_caveat_and_different_addresses_no_shared_caveat():
    c = run([crow(role="CorporateOwner", name="X LLC", addr="1 A ST"), crow(role="IndividualOwner", name="Y", addr="2 B ST")])
    assert "agent_not_owner" not in codes(c) and "shared_address_not_evidence" not in codes(c)


def test_registration_without_contacts_says_so():
    c = run([], rows=[row(rid=100), row(rid=101)])
    assert "no_contacts_found" in codes(c) and all(not g.contacts for g in c.buildings[0].registrations)


def test_building_without_registration_has_no_contacts_and_no_contact_caveats():
    c = run([], rows=[dict(bin="1", address="1 MAIN ST", registrationId=None, lastRegistered=None, registrationEnd=None)])
    assert c.buildings[0].registrations == () and "no_registration_found" in codes(c) and "role_as_recorded" in codes(c)


@pytest.mark.parametrize("kw, expected", [
    (dict(outcome=P.Match.AMBIGUOUS, bbl=None, in_graph=None, candidates=("MAIN ST", "MAIN AVE")), P.CAVEAT_AMBIGUOUS),
    (dict(in_graph=False), P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001")),
])
def test_unresolved_reads_nothing(kw, expected):
    c = run([crow()], **kw)
    assert c.lot is None and c.buildings == () and expected in c.caveats and "role_as_recorded" not in codes(c)


# ---- tool view and contract ------------------------------------------------------------------------------------------

def tool(contacts=(), rows=None):
    return T.make_building_contacts_tool(FakeClient(resolved()), FakeGraph(), FakeCG(contacts, rows=[row()] if rows is None else rows))


ARGS = {"address": "1 Main St", "borough": "Manhattan"}


def test_tool_name_and_description_for_the_model():
    t = tool()
    text = " ".join(t.description.split())
    assert t.name == "building_contacts" and set(t.args) == {"address", "borough", "zip_code"}
    assert "only with the role recorded" in text and 'never "the owner"' in text


def test_tool_lists_contact_buildings_with_roles_and_no_owner_keys():
    out = tool([crow(role="Agent"), crow(role="HeadOfficer", name="BAOZHEN CHEN", title="PRESIDENT")]).invoke(ARGS)
    (b,) = out["contact_buildings"]
    assert out["status"] == "ok" and b["bin"] == "1" and b["addressed"] is True
    assert [(c["role"], c["name"], c["title"]) for c in b["registrations"][0]["contacts"]] == [
        ("Agent", "JAY WONG", None), ("HeadOfficer", "BAOZHEN CHEN", "PRESIDENT")]
    assert not {"owner", "owners", "same_party", "total", "score"} & set(b["registrations"][0])


def test_tool_caps_contacts_and_says_so():
    out = T.contacts_to_dict(build_contacts(answer(), FakeCG([crow(name=f"P{i}") for i in range(5)], rows=[row()])), max_contacts=2)
    assert len(out["contact_buildings"][0]["registrations"][0]["contacts"]) == 2
    assert "contacts_capped" in {c["code"] for c in out["caveats"]}


def test_tool_statuses_are_answers_not_exceptions():
    out = T.make_building_contacts_tool(FakeClient(error=RuntimeError("x")), FakeGraph(), FakeCG()).invoke(ARGS)
    assert out["status"] == "error" and "RuntimeError" in out["message"]


def test_assemble_points_at_one_building_and_carries_caveats():
    out = tool([crow(role="Agent")]).invoke(ARGS)
    m = ModelAnswer(kind="contacts", summary="HPD lists JAY WONG as the agent.", facts=[
        ModelFact(statement="JAY WONG is recorded as the Agent.", evidence=[EvidenceRef(section="contacts", bin="1")]),
        ModelFact(statement="No building 9 listed.", evidence=[EvidenceRef(section="contacts", bin="9")])])
    a = assemble(m, [out])
    assert a.facts[0].evidence[0].bin == "1" and a.facts[1].unresolved
    assert {"role_as_recorded", "agent_not_owner"} <= a.caveat_codes


def test_neo4j_contact_graph_read_is_parameterized_and_limited():
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params))
            return Res()

    C.Neo4jContactGraph(Drv(), "watchline").contacts("3008260002")
    (q, params), = seen
    assert q.timeout and "$bbl" in q.text and "3008260002" not in q.text and "$limit" in q.text and params["bbl"] == "3008260002"
