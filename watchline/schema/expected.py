"""What the code reads from the graph. Keep in step with the Cypher in `watchline/`; `tests/test_schema_manifest.py`
fails when a query uses a label, relationship type or property that is not listed here.

NODES maps a graph label to the properties read from it. RELS maps a relationship type to
(start label, end label, properties read from the relationship); a type listed with several endpoint pairs is
one entry per pair.
"""

NODES: dict[str, set[str]] = {
    "Lot": {"bbl", "address", "yearBuilt", "buildingClass", "unitsRes", "assessedTotal", "plutoNumBuildings", "hpdRegistered"},
    "Building": {"bin", "address"},
    "Registration": {"registrationId"},
    "Contact": {"contactType", "corporationName", "personName", "title", "mailingAddress", "addressLine2", "zip", "nameKey"},
    "Deed": {"documentId", "docType", "docDate", "recordedDate", "amount"},
    "Grantee": {"name", "nameKey", "mailingAddress", "addressLine2", "zip"},
    "Grantor": {"name"},
    "Violation": {"violationClass", "status", "inspectionDate"},
    "Problem": {"majorCategory", "duplicate"},
    "Litigation": {"litigationId", "caseType", "caseOpenDate", "caseStatus", "openJudgement", "harassmentFinding",
                   "findingDate", "penalty", "respondent", "respondentKeys"},
    "DosEntity": {"nameKey", "dosId", "name", "entityType", "jurisdiction", "filingDate", "processName", "processAddress",
                  "processAddressLine2", "processCity", "processState", "processZip", "agentName", "agentAddress",
                  "agentAddressLine2", "agentCity", "agentState", "agentZip", "processAddressEntities"},
    "Landlord": {"nodeId", "name", "businessAddresses"},
    "NetworkMaskedAddress": {"address", "degree"},
    "PortfolioMaskedAddress": {"address", "degree"},
    "MailDropAddress": {"address", "kind", "zip5", "reviewStatus"},
}

RELS: dict[str, list[tuple[str, str, set[str]]]] = {
    "HAS_BUILDING": [("Lot", "Building", set())],
    "HAS_REGISTRATION": [("Building", "Registration", {"lastRegistered", "registrationEnd"})],
    "HAS_CONTACT": [("Registration", "Contact", set())],
    "HAS_DEED": [("Lot", "Deed", set())],
    "HAS_GRANTEE": [("Deed", "Grantee", set())],
    "HAS_GRANTOR": [("Deed", "Grantor", set())],
    "HAS_VIOLATION": [("Building", "Violation", set())],
    "HAS_PROBLEM": [("Building", "Problem", set())],
    "HAS_LITIGATION": [("Building", "Litigation", set())],
    "COVERS": [("Landlord", "Lot", set())],
    "CONNECTED_BY_IDENTITY": [("Landlord", "Landlord", set())],
    "CONNECTED_BY_ADDRESS": [("Landlord", "Landlord", {"weight"})],
    "CONNECTED_BY_NAME": [("Landlord", "Landlord", {"weight"})],
}
