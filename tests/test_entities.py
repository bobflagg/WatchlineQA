"""Entity research (Q5): the DOS lookup and its section template. Fake rows; no graph, no model."""
from test_profile import LOT, answer
from test_report_full import dos_row

from watchline.entities import dos as D
from watchline.entities.dos import build_entities, entities_view
from watchline.profile import profile as P
from watchline.report import sections as S


class FakeEG:
    def __init__(self, owners=(), grantees=(), dos=(), lot=LOT):
        self._lot, self._o, self._g, self._d = lot, [dict(name=n, key=k) for n, k in owners], [dict(name=n, key=k) for n, k in grantees], list(dos)
        self.asked = []

    def lot(self, bbl): return self._lot
    def owner_entities(self, bbl): return self._o
    def latest_grantees(self, bbl): return self._g

    def dos_records(self, keys):
        self.asked.append(list(keys))
        return [r for r in self._d if r["key"] in keys]


def run(**kw):
    return build_entities(answer(), FakeEG(**kw))


def codes(x):
    return {c.code for c in x.caveats}


def section(**kw):
    return S.entity_research(entities_view(run(**kw)))


def test_a_name_with_a_record_a_name_without_one_and_an_individual_grantee():
    x = run(owners=[("ACME LLC", "ACME LLC")], grantees=[("ACME LLC", "ACME LLC"), ("OTHER HOLDINGS LLC", "OTHER HOLDINGS LLC"), ("DOE, JANE", "DOE JANE")], dos=[dos_row()])
    assert [(s.name, s.roles, len(s.records)) for s in x.subjects] == [("ACME LLC", ("registered owner", "latest deed grantee"), 1), ("OTHER HOLDINGS LLC", ("latest deed grantee",), 0)]
    assert x.skipped == 1 and {"dos_process_not_operator", "name_match_not_identity", "dos_no_record_not_absence", "individuals_not_looked_up"} <= codes(x)
    assert x.sources == (D.DOS,)


def test_the_lookup_is_by_name_key_and_asks_for_every_key_at_once():
    eg = FakeEG(owners=[("ACME LLC", "ACME LLC")], grantees=[("NEW CO LLC", "NEW CO LLC")], dos=[])
    build_entities(answer(), eg)
    assert eg.asked == [["ACME LLC", "NEW CO LLC"]]


def test_the_record_carries_its_fields_and_joins_the_address_parts():
    (rec,) = run(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(processAddress="350 MOTOR PKWY 204")]).subjects[0].records
    assert (rec.dosId, rec.filingDate, rec.processAddress, rec.processAddressEntities) == (5857246, "2020-10-14", "350 MOTOR PKWY 204, STATEN ISLAND, NY, 10304", 5)


def test_several_records_with_one_name_are_all_shown_and_none_chosen():
    x = run(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(dos_id=1), dos_row(dos_id=2)])
    assert [r.dosId for r in x.subjects[0].records] == [1, 2] and "dos_several_records" in codes(x)


def test_the_statutory_default_process_name_and_a_shared_process_address_are_flagged():
    x = run(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(processName="THE LIMITED LIABILITY COMPANY")])
    assert {"dos_default_process_name", "shared_address_not_evidence"} <= codes(x)
    y = run(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(processAddressEntities=1)])
    assert "shared_address_not_evidence" not in codes(y) and "dos_default_process_name" not in codes(y)


def test_nothing_to_look_up_says_so_and_asks_for_no_records():
    eg = FakeEG(owners=[], grantees=[("DOE, JANE", "DOE JANE")])
    x = build_entities(answer(), eg)
    assert x.subjects == () and x.skipped == 1 and {"no_entity_names", "individuals_not_looked_up"} <= codes(x)
    a = S.entity_research(entities_view(x))
    assert a.kind == "entities" and "There is no entity name to look up" in a.summary and not a.facts


def test_an_unresolved_address_or_a_missing_lot_reads_nothing():
    eg = FakeEG(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row()])
    x = build_entities(answer(in_graph=False), eg)
    assert x.subjects == () and P.CAVEAT_NOT_IN_GRAPH.format(bbl="1000010001") in x.caveats and eg.asked == []
    assert build_entities(answer(), FakeEG(lot=None)).lot is None


# ---- the section ------------------------------------------------------------------------------------------------------------------

def test_the_section_words_a_match_as_a_lead_and_a_miss_as_not_proof_of_absence():
    a = section(owners=[("ACME LLC", "ACME LLC")], grantees=[("OTHER HOLDINGS LLC", "OTHER HOLDINGS LLC")], dos=[dos_row()])
    t = " ".join([a.summary, *(f.statement for f in a.facts)])
    assert a.kind == "entities" and "2 entity names looked up in the New York active-entity snapshot: 1 with a record, 1 with none." in a.summary
    assert ("ACME LLC (registered owner) is a lead for DOS record 5857246, found by the same name: Domestic Limited Liability Company, New York, filed 2020-10-14. "
            "The state forwards legal papers to ACME LLC at 5 CROMWELL CIRCLE, STATEN ISLAND, NY, 10304. Registered agent: none listed. "
            "5 entities in the snapshot share this process address.") in t
    assert "OTHER HOLDINGS LLC (latest deed grantee): no record in the New York active-entity snapshot under this name (looked up as OTHER HOLDINGS LLC)" in t
    assert "not a statement that the entity does not exist" in t and "is the owner" not in t.replace("not proof that the DOS entity is the owner", "")
    assert all(f.evidence[0].section == "dos_records" for f in a.facts) and D.DOS in a.sources


def test_a_person_as_process_name_is_shown_with_that_role_and_the_default_name_is_not_a_person():
    t = " ".join(f.statement for f in section(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(processName="MEILYN MARTINEZ")]).facts)
    assert "The state forwards legal papers to MEILYN MARTINEZ at" in t
    t = " ".join(f.statement for f in section(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(processName="THE COMPANY")]).facts)
    assert "to THE COMPANY (the statutory default name, not a person) at" in t


def test_a_registered_agent_is_shown_with_its_address_when_listed():
    t = " ".join(f.statement for f in section(owners=[("ACME LLC", "ACME LLC")], dos=[dos_row(agentName="CT CORPORATION SYSTEM", agentAddress="28 LIBERTY ST", agentCity="NEW YORK",
                                                                                         agentState="NY", agentZip="10005")]).facts)
    assert "Registered agent: CT CORPORATION SYSTEM at 28 LIBERTY ST, NEW YORK, NY, 10005." in t


def test_the_section_is_deterministic_and_has_the_caveats():
    kw = dict(owners=[("ACME LLC", "ACME LLC")], grantees=[("OTHER HOLDINGS LLC", "OTHER HOLDINGS LLC")], dos=[dos_row()])
    assert section(**kw) == section(**kw) and {"dos_process_not_operator", "dos_no_record_not_absence"} <= {c.code for c in section(**kw).caveats}


def test_the_neo4j_reads_are_parameterized_and_limited():
    seen = []

    class Res:
        records = []

    class Drv:
        def execute_query(self, q, params, **kw):
            seen.append((q, params))
            return Res()

    g = D.Neo4jEntityGraph(Drv(), "watchline")
    g.owner_entities("1000010001")
    g.latest_grantees("1000010001")
    g.dos_records(["ACME LLC"])
    assert len(seen) == 3
    for q, params in seen:
        assert q.timeout and "$limit" in q.text and "ACME" not in q.text and "1000010001" not in q.text and params
    assert seen[2][1]["keys"] == ["ACME LLC"]


# ---- live (no model): the demo lots and the spec's anchors --------------------------------------------------------------------------

def test_live_dos_records_for_the_demo_lots_and_the_spec_anchors(live_report_deps):
    """Probed 2026-11-25 with separate queries. 5413 Plaza LLC is the spec's anchor A (DOS 5857246, filed 2020-10-14); 438 52 St Owners Corp is anchor C (no record under the HPD
    spelling, a record under the deed spelling)."""
    from watchline.entities.dos import entity_research
    d = live_report_deps

    def facts(address):
        x = S.entity_research(entities_view(entity_research(d.client, d.graph, d.rg, address)))
        return " ".join(f.statement for f in x.facts), x
    t, x = facts("2141 Washington Avenue, Bronx")
    assert "2141 WASHINGTON AVE LLC (registered owner): no record in the New York active-entity snapshot" in t
    assert "2141 WASHINGTON LLC (latest deed grantee) is a lead for DOS record 5656155, found by the same name: Domestic Limited Liability Company, New York, filed 2019-11-14" in t
    assert "153-08 79TH AVENUE, FLUSHING, NY, 11367" in t and {"dos_no_record_not_absence", "dos_process_not_operator"} <= {c.code for c in x.caveats}
    t, x = facts("74 Clinton Place, Bronx")
    assert "74 CLINTON PLACE LLC (registered owner and latest deed grantee) is a lead for DOS record 5788221" in t and "350 MOTOR PKWY 204, HAUPPAUGE, NY, 11788" in t
    assert "74 CLINTON HOLDINGS LLC (latest deed grantee) is a lead for DOS record 5349064" in t and "legal papers to MEILYN MARTINEZ at 442-E LORIMER STREET STE# 268" in t
    assert "36 entities in the snapshot share this process address" in t and "shared_address_not_evidence" in {c.code for c in x.caveats}
    t, _ = facts("5413 7 Avenue, Brooklyn")
    assert "5413 PLAZA LLC (registered owner and latest deed grantee) is a lead for DOS record 5857246" in t and "filed 2020-10-14" in t and "Registered agent: none listed" in t
    t, _ = facts("438 52 Street, Brooklyn")
    assert "438 52 ST OWNERS CORP (registered owner): no record" in t and "438 52ND ST OWNERS CORP (latest deed grantee) is a lead for DOS record 2733264" in t
