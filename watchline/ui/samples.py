"""Sample questions for the sidebar pulldown. Each runs in the chat as if typed. Addresses are ones the tools have been checked on."""

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
}

PLACEHOLDER = "Sample questions"
