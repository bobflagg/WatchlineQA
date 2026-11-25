"""Sample queries for the sidebar pulldowns: the keys are the competency questions (first pulldown), the values the queries
under each (second pulldown). Each query runs in the chat as if typed. Addresses are ones the tools have been checked on."""

SAMPLE_QUESTIONS: dict[str, tuple[str, ...]] = {
    "Q1: building profile": (
        "Give me a profile of 224 54 Street, Brooklyn.",
        "How many buildings are on the lot at 17 Battery Place, Manhattan?",
        "What has been cited, reported or brought at 21-08 Nameoke Avenue, Queens?",
    ),
    "Q2: registered owner": (
        "Who is the registered owner of 5413 7 Avenue, Brooklyn?",
        "Who is the registered owner of each building at 224 54 Street, Brooklyn?",
        "When did the HPD registration at 234 54 Street, Brooklyn end?",
        "Who owns 70 Broad Street, Manhattan?",
    ),
    "Q3: deed grantee against HPD owner": (
        "Who is the grantee on the most recent deed for 5413 7 Avenue, Brooklyn, and is it the HPD registered owner?",
        "Does the deed grantee at 548 52 Street, Brooklyn match the HPD registered owner?",
    ),
    "Q4: managing agent and contacts": (
        "Who is the managing agent for 5413 7 Avenue, Brooklyn, and is that person the owner?",
        "Who is the site manager at 5413 7 Avenue, Brooklyn?",
        "Who are the HPD contacts for 2141 Washington Avenue, Bronx, and in what roles?",
    ),
    "Q12: deed history": (
        "What deeds have been recorded for 2141 Washington Avenue, Bronx?",
        "What deeds were recorded for 5413 7 Avenue, Brooklyn since 2015?",
        "How many times has 2141 Washington Avenue in the Bronx changed hands, and how many of those were sales?",
    ),
    "Q15: open violations": (
        "What are the open violations at 438 52 Street, Brooklyn?",
        "How many open violations per unit does 74 Clinton Place, Bronx have?",
        "What is the rate of open violations per residential unit at 126 Pearl Street, Manhattan?",
    ),
    "Q28: litigation": (
        "What Housing Court cases has HPD brought against 74 Clinton Place, Bronx?",
        "Was there a harassment finding in the Housing Court case at 438 52 Street, Brooklyn?",
        "Is the respondent in the Housing Court case at 20 Beaver Street, Manhattan the building's owner?",
    ),
}


# Addresses for the report page's pulldown (first the one the demo leads with), each with what the report shows for it. All were run end to end on the live graph.
REPORT_SAMPLES: dict[str, str] = {
    "2141 Washington Avenue, Bronx": "the lot of the misspelled BADHUMI record: one lead, to the BAHUMI portfolio (1 lot becomes 56 if accepted)",
    "74 Clinton Place, Bronx": "a BAHUMI lot: 15 open violations over 3 units and one harassment finding on a case at the building",
    "5413 7 Avenue, Brooklyn": "no landlord record covers the lot, so there is no portfolio; owner, contacts, deeds and conditions still show",
}
