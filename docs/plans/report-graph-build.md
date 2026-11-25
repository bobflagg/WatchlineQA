# Plan: the report graph (PESP report, demo mid-January 2027)

## Context
Every PESP section now exists as a deterministic function (Q1, Q2, Q3, Q4, Q12.1, Q15, Q28, and the identity checkpoint), but only the
identity checkpoint is a graph, and it stands alone (`watchline/report/graph.py`). The demo (JustFix and the Housing Data Coalition) needs
one run that takes a building address, produces the sections in PESP order, pauses once for the researcher's accept or reject, and exports a report
that reads well for organizers with the evidence and caveats one click away. No model is called anywhere in this plan, so it costs nothing to
run. Narrative (generated prose behind the firewall) is a later step and is not part of this plan.

Decisions already made (you, today): **entry point = a building address**; **decisions are made on a Streamlit report page**; **export = Markdown plus the
JSON decision log**.

## The run, in PESP order (one LangGraph workflow, state is plain JSON)
| Node | PESP step | Calls (existing) | Pause? |
|---|---|---|---|
| `resolve` | 1 address | `resolve_text` (`watchline/geosupport/resolution.py:168`) | Yes, if the street is ambiguous or the borough is missing: the researcher picks, then it resolves again |
| `building_facts` | 2 | `build_profile` | no |
| `owner_and_contacts` | 3 | `build_registrations`, `build_contacts` | no |
| `deed_history` | 4 | `build_timeline`, `build_comparison` (latest deed against the registered owner) | no |
| `entity_research` | 5 | not built (Q5, DOS) | no: a "not yet covered" section saying what the graph cannot say |
| `landlords` then `propose` and `decide` | 6, 7 | new read `landlords_covering(bbl)`, then `identity_checkpoint` (existing) | **Yes**: accept or reject each lead (one decision per pair). More than one landlord name on the lot: the researcher picks which to check. None: a "no landlord record covers this lot" section |
| `conditions` | 8 | `build_violations`, `build_litigation` | no |
| `web_research` | 9 | not built | no: "not yet covered" |
| `assemble` | 10 | joins the sections | no (the researcher's takeaway is typed on the page and added at export, labelled as theirs) |

All section nodes take the one `Answer` from `resolve`, so Geosupport is called once, not once per section (the existing `build_*` functions
already take a resolution; the `building_*` wrappers resolve again and are not used).

## What gets built (reuse first)
- **Section templates (no model):** `watchline/report/sections.py` turns each section's dataclass into an `Answer` (kind, summary, facts with evidence, caveats,
  sources), written in plain language and following the same pattern as `watchline/identity/section.py:to_answer`. Reuse the JSON views and caps in
  `watchline/agent/tools.py` (`profile_to_dict`, `registrations_to_dict`, `contacts_to_dict`, `timeline_to_dict`, `violations_to_dict`, `litigation_to_dict`) as the evidence data, so a
  237-building lot stays readable (first 25 buildings, "N more", counts for all).
- **Graph:** extend `watchline/report/graph.py` (the identity pause stays as it is) into `build_report_graph(deps, checkpointer)` with the nodes above. `deps` bundles the
  client, the Geosupport graph, and the read-only graph objects (`Neo4jTimelineGraph` already serves registrations, deeds, timeline, contacts and conditions; the identity reads
  are `Neo4jIdentityGraph`, which gets `landlords_covering`). State holds the input text, the resolution, the sections (ordered), the decisions and the log.
- **Snapshot and reproducibility:** the report records the sources with their snapshot dates (they are already on each Answer), the decisions, and a `generated_at`
  that the caller supplies (never the clock), so the same inputs give the same file byte for byte.
- **Export:** `watchline/report/export.py` renders the report to Markdown: a header (address, lot, snapshot dates, "sections are reproducible; no generated narrative"), the
  five PESP questions as headings (Who is my landlord? How many properties and where? Do they hold or sell? What are the conditions? Is there news?) with the sections under them, each
  with its leads and caveats inline, the decisions (role, date, note) and the researcher's takeaway. It writes `report.md` and `decisions.json` into `build/reports/<address slug>/`.
  Reuse `render_markdown` in `watchline/agent/answer.py`.
- **Command line:** `make report ADDRESS="..." [DECISIONS=file.json]`. With a decisions file it resumes the pause itself and writes the files: this is the **backup run** for the talk
  and the way to check reproducibility. Without one it stops at the pause and prints the leads.
- **Streamlit report page:** `watchline/ui/report_page.py`, linked from the app (load `developing-with-streamlit` and `watchline-ui` before writing it). Enter an address, see the
  sections appear with `render_answer`, answer the pause (an expander per lead with its evidence, Used or Set aside, then accept or reject, a role, a note), then see the final report with the
  portfolio footprint as held next to as decided, a takeaway box, and download buttons for the Markdown and the decision log. Kinds and lead pills follow
  `.claude/skills/watchline-ui/references/answer-rendering.md`.

## Slices (each a small commit, the process loop for each)
1. **Section templates** for steps 2 to 4 and 8 on fake rows, with tests. Then the "not yet covered" sections.
2. **Graph:** resolve (with the address pause), `landlords_covering`, the section nodes, the identity pause, assemble. Tests on fakes: order, pauses, resume, restart, determinism.
3. **Export and `make report`:** Markdown renderer, files, decisions file resume. Snapshot tests on fake rows.
4. **Streamlit page** with an `AppTest` per state (before the pause, at the pause, finished), using an injected fake graph (the page must take its dependencies as a parameter).
5. **Live checks (no model):** the demo addresses end to end on the live graph and sidecar, numbers verified by hand against the graph, and the backup run saved.
6. **Docs:** update `docs/plans/demo-slices.md`, save this plan as `docs/plans/report-graph-build.md`, add an explainer for the report flow (pipeline-explainer skill), and the `status.md` entry.

## Tests (all without model calls)
- Fake-row unit tests per section template (facts, evidence tags, caveat codes carried through, nothing summed, harassment finding only for After Inquest or After Trial,
  amount 0 never a sale, a respondent match always a lead).
- Graph tests with the existing fakes (`FakeClient`, `FakeGraph`, `FakePG`, `FakeRG`, `FakeCG`, `FakeIG`): section order, the address and decision pauses, a bad answer sent back, no landlord
  record, several landlord names, the same decisions giving identical files, resume on a new graph object.
- Export: golden Markdown on fake rows; the file names; the "not yet covered" lines; no model text in the file.
- UI: `AppTest` for the report page states; a test that every caveat of every section appears on the page and in the export.
- Live (needs Neo4j and the sidecar, no model): 2141 Washington Avenue and 74 Clinton Place full reports; check the numbers listed under Demo addresses.

## Demo addresses (to confirm before slice 5)
- **2141 Washington Avenue, Bronx**: the lot the BADHUMI record covers. Registered owner `2141 WASHINGTON AVE LLC` with BADHUMI as HeadOfficer and BAHUMI as Officer and Shareholder on
  registration 205148; the 2020 deed to `2141 WASHINGTON LLC`; seven old deeds with amount 0; the checkpoint starts from BADHUMI (1 lot, 3 units) and one accept brings in the BAHUMI
  portfolio (56 lots, 179 units). This is the strongest story for the checkpoint.
- **74 Clinton Place, Bronx**: a BAHUMI lot. 15 open violations over 3 units, and the one After Trial finding (respondent an individual, not the owner), which must read as a finding about the building.
- Not covered: lots no landlord record covers (for example 5413 7 Avenue) get the "graph has no landlord record" section.

## Risks and open points
- A lot covered by several landlord names needs the picker; the demo addresses have one each, so this is tested on fakes only.
- `interrupt()` re-runs the whole pausing node on resume: the nodes that pause must read nothing before the pause (the existing identity node already follows this).
- The in-memory checkpointer lasts for the process: the saved decision log and the backup run are the durable record for the demo.
- Berkovics (11 leads) is unchanged; not a demo address until you decide.
- Complaints (Q27), pests (Q15.3) and entity research (Q5) stay "not yet covered" until their specs and data are in.

## Verification
`make check`; `make test-live` and `make eval` (no model); `make report ADDRESS="2141 Washington Avenue, Bronx" DECISIONS=<file>` run twice and the two outputs compared (identical);
`make ui` and the report page by hand on both demo addresses; every number on the page checked against the graph by hand before the talk.
