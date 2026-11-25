"""Hand-built answers, one per kind, for looking at the page without the model, the graph or the sidecar."""
from watchline.agent.answer import Answer, CaveatOut, Evidence, Fact
from watchline.contacts import contacts as _contacts
from watchline.deeds import deeds as _deeds
from watchline.deeds import timeline as _timeline
from watchline.registration import registration as _reg

_BUILDING = {"bin": "3000001", "address": "1 Example Street", "violations_by_class": {"A": 2, "B": 5, "C": 1}}
_CAVEATS = [
    CaveatOut(code="violations-cited", text="Violations are what was cited, not findings of fault."),
    CaveatOut(code="lot-wide", text="Units and assessed value belong to the lot, not to any one building."),
    CaveatOut(code="hpd-only", text="Violations exist only for HPD-registered buildings; none recorded is not a clean record."),
]

_REGISTRATION = {"bin": "3000001", "address": "1 Example Street", "addressed": True, "registrations": [
    {"registrationId": 100001, "lastRegistered": "2025-09-30", "registrationEnd": "2026-09-01",
     "owners": [{"contactType": "CorporateOwner", "name": "EXAMPLE HOUSING LLC"}]},
    {"registrationId": 100002, "lastRegistered": None, "registrationEnd": "2025-09-01", "owners": []}]}
_REGISTRATION_CAVEATS = [CaveatOut(code=c.code, text=c.text) for c in
                         (_reg.CAVEAT_NOT_TITLE, _reg.CAVEAT_PERIOD, _reg.CAVEAT_OTHER_ROLES, _reg.CAVEAT_NO_OWNER)]

_DEEDS = [{"documentId": "2018000000000001", "docType": "DEED", "docDate": "2018-09-26", "recordedDate": "2018-10-18", "amount": 4000000,
           "otherLots": 0, "grantees": [{"name": "EXAMPLE REALTY LLC", "mailingAddress": "14 Sinclair Dr", "addressLine2": None, "zip": "11024"},
                                        {"name": "K S EXAMPLE LLC", "mailingAddress": "14 Sinclair Dr", "addressLine2": None, "zip": "11024"}]}]
_COMPARISON = [{"documentId": "2018000000000001", "grantee": "K S EXAMPLE LLC", "owner": "KS Example LLC", "ownerType": "CorporateOwner",
                "nameAgreement": {"outcome": "different", "rule": None},
                "addressAgreement": {"outcome": "differs", "rule": "A1",
                                     "grantee": {"mailingAddress": "14 Sinclair Dr", "addressLine2": None, "zip": "11024"},
                                     "owner": {"mailingAddress": "1 Owner Rd", "addressLine2": None, "zip": "11361"}}}]
_DEED_CAVEATS = [CaveatOut(code=c.code, text=c.text) for c in
                 (_deeds.CAVEAT_NAME_NOT_IDENTITY, _deeds.CAVEAT_RECORDED, _deeds.CAVEAT_SNAPSHOTS)]

_TIMELINE = [
    {"documentId": "2020000000000001", "docType": "DEED", "docDate": "2019-12-24", "recordedDate": "2020-01-09", "amount": 549855,
     "notSale": False, "otherLots": 0, "grantors": ["EXAMPLE BANK N.A."], "grantorRows": 1, "grantees": ["EXAMPLE HOLDINGS LLC"], "granteeRows": 1},
    {"documentId": "BK_7820000000001", "docType": "DEED", "docDate": "1978-08-08", "recordedDate": "1978-08-08", "amount": 0,
     "notSale": True, "otherLots": 1075, "grantors": ["CITY OF EXAMPLE", "CITY OF EXAMPL"], "grantorRows": 27,
     "grantees": ["CITY OF EXAMPLE"], "granteeRows": 14}]
_TIMELINE_COUNTS = {"deeds": 2, "notSale": 1, "amountZero": 1, "byType": {"DEED": 2}, "since": None, "until": None}
_TIMELINE_CAVEATS = [CaveatOut(code=c.code, text=c.text) for c in
                     (_timeline.CAVEAT_ORDER, _timeline.CAVEAT_PARTY_NAMES, _deeds.CAVEAT_NOT_SALE, _deeds.CAVEAT_MULTI_LOT)]

_CONTACTS = {"bin": "3000001", "address": "1 Example Street", "addressed": True, "registrations": [
    {"registrationId": 100001, "lastRegistered": "2025-09-30", "registrationEnd": "2026-09-01", "contacts": [
        {"role": "Agent", "name": "PAT EXAMPLE", "title": None, "mailingAddress": "9 Office Rd", "addressLine2": None, "zip": "11220"},
        {"role": "HeadOfficer", "name": "SAM SAMPLE", "title": "PRESIDENT", "mailingAddress": "9 Office Rd", "addressLine2": None, "zip": "11220"},
        {"role": "SiteManager", "name": "PAT EXAMPLE", "title": None, "mailingAddress": None, "addressLine2": None, "zip": None}]}]}
_CONTACT_CAVEATS = [CaveatOut(code=c.code, text=c.text) for c in
                    (_contacts.CAVEAT_ROLE_AS_RECORDED, _contacts.CAVEAT_AGENT_NOT_OWNER, _deeds.CAVEAT_SHARED_ADDRESS)]

FIXTURES: dict[str, Answer] = {
    "profile": Answer(
        kind="profile", summary="The lot at 1 Example Street, Brooklyn has one registered building with 8 violations cited.",
        facts=[Fact(statement="The building has 2 class A, 5 class B and 1 class C violations cited.",
                    evidence=[Evidence(section="buildings", bin="3000001", bbl="3000010001", data=_BUILDING)]),
               Fact(statement="The lot has 12 residential units.",
                    evidence=[Evidence(section="characteristics", bbl="3000010001", data={"unitsRes": 12})])],
        caveats=_CAVEATS, sources=["HPD violations, release 26v1", "PLUTO 25b"]),
    "registration": Answer(
        kind="registration",
        summary="HPD lists two registrations for the building at 1 Example Street. One records a registered owner; the other records none.",
        facts=[Fact(statement="Registration 100001 was last registered 2025-09-30, ends 2026-09-01, and records EXAMPLE HOUSING LLC as a "
                              "corporate owner.",
                    evidence=[Evidence(section="registrations", bin="3000001", bbl="3000010001", data=_REGISTRATION)]),
               Fact(statement="Registration 100002 has no last-registered date, ends 2025-09-01, and records no owner contact.",
                    evidence=[Evidence(section="registrations", bin="3000001", bbl="3000010001", data=_REGISTRATION)])],
        caveats=_REGISTRATION_CAVEATS, sources=["HPD registrations (data through 2026-05-29)"]),
    "ownership_comparison": Answer(
        kind="ownership_comparison",
        summary="The most recent deed names two grantees. Neither grantee's name matches the HPD registered owner as recorded.",
        facts=[Fact(statement="Deed 2018000000000001 was recorded 2018-10-18 (document date 2018-09-26) for an amount of 4000000, with "
                              "grantees EXAMPLE REALTY LLC and K S EXAMPLE LLC.",
                    evidence=[Evidence(section="deeds", bbl="3000010001", data=_DEEDS)]),
               Fact(statement="K S EXAMPLE LLC and the registered owner KS Example LLC differ as recorded; the addresses differ.",
                    evidence=[Evidence(section="comparison", bbl="3000010001", data=_COMPARISON)])],
        caveats=_DEED_CAVEATS,
        sources=["ACRIS deeds and parties (data through 2026-05-31)", "HPD registrations (data through 2026-05-29)"]),
    "contacts": Answer(
        kind="contacts",
        summary="HPD lists three contacts on the building's one registration: an agent, a head officer and a site manager.",
        facts=[Fact(statement="PAT EXAMPLE is recorded as the Agent, at 9 Office Rd.",
                    evidence=[Evidence(section="contacts", bin="3000001", bbl="3000010001", data=_CONTACTS)]),
               Fact(statement="SAM SAMPLE is recorded as the HeadOfficer, with the title PRESIDENT.",
                    evidence=[Evidence(section="contacts", bin="3000001", bbl="3000010001", data=_CONTACTS)]),
               Fact(statement="PAT EXAMPLE is also recorded as the SiteManager, with no address.",
                    evidence=[Evidence(section="contacts", bin="3000001", bbl="3000010001", data=_CONTACTS)])],
        caveats=_CONTACT_CAVEATS, sources=["HPD registrations (data through 2026-05-29)"]),
    "timeline": Answer(
        kind="timeline",
        summary="Two deeds are recorded on the lot. One of them is not a sale because its amount is 0.",
        facts=[Fact(statement="Two deeds are recorded; one has an amount of 0, which is not a sale.",
                    evidence=[Evidence(section="timeline_counts", bbl="3000010001", data=_TIMELINE_COUNTS)]),
               Fact(statement="The newest deed, 2020000000000001, was recorded 2020-01-09 for an amount of 549855, from EXAMPLE BANK N.A. "
                              "to EXAMPLE HOLDINGS LLC.",
                    evidence=[Evidence(section="timeline", bbl="3000010001", data=_TIMELINE)]),
               Fact(statement="The 1978 deed also names 1075 other lots.",
                    evidence=[Evidence(section="timeline", bbl="3000010001", data=_TIMELINE)])],
        caveats=_TIMELINE_CAVEATS, sources=["ACRIS deeds and parties (data through 2026-05-31)"]),
    "caveats": Answer(
        kind="profile", summary="One building is listed. A fact points at data the tools did not return.",
        facts=[Fact(statement="The building has open litigation.", unresolved=[{"section": "counts"}])],
        caveats=_CAVEATS, sources=["HPD litigation, release 26v1"]),
    "empty": Answer(kind="profile", summary="The lot is not HPD-registered, so no buildings or violations are listed."),
    "clarification": Answer(kind="clarification", summary="Which borough is 1 Example Street in?",
                            caveats=[], sources=[]),
    "not_found": Answer(kind="not_found", summary="No tax lot matched that address."),
    "refusal": Answer(kind="refusal", summary="The records cannot say whether a landlord is at fault; they show what was cited."),
    "error": Answer(kind="error", summary="The lookup failed. Nothing was answered; try again."),
}
