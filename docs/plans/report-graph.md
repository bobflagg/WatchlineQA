# Report graph and product split (direction agreed 2026-11-24; details open)

Status: direction agreed in discussion on 2026-11-24; the sequence and dates below are still a proposal.
Source for the report procedure: the PESP "How to Research Your Landlord" guide (May 2026, Strategic
Landlord Research Guide).

## Decisions so far

- **Two products** on one shared question library (below). The report graph is a demo piece first.
- **Demo:** mid-January 2027, to JustFix (Who Owns What) and the Housing Data Coalition of NYC. The audience
  includes organizers and other non-technical staff, so the report must read well in plain language, and
  the evidence and caveats must be one click away for the data people.
- **Reproducible sections now, generated narrative later.** The report has two layers (next section).
- **Evidence first for this audience.** They know the data and care about leads versus findings. The
  confirm-or-reject checkpoint on a name match is the centrepiece of the demo.

## Two layers: sections and narrative

- **Sections (deterministic, reproducible).** Each question function returns a structured section (kind,
  facts, evidence, caveat codes, sources). The report graph assembles them in the PESP order. The same
  inputs on the same graph snapshot give the same sections, so they can be snapshot-tested and re-run
  exactly. Record the graph snapshot (or load date) and the researcher's checkpoint decisions in the report.
- **Narrative (optional, generated, swappable model).** A model reads the sections and writes the intro,
  connecting prose and summary. It may vary run to run, so the report labels sections as reproducible and
  narrative as generated. Later a more powerful model can write it.
- **The firewall.** The narrative step may not change facts. Its output passes the same deterministic
  checks as agent answers: caveat codes carried through, no summed severity, no identity-asserting phrasing
  (a name match is a lead), and every number and name must trace to a section. A stronger model can then be
  swapped in without risking a dropped caveat. Early development ships sections only.

## Demo-first sequence (proposal; about seven weeks)

1. **By early December:** lock the section contract (Q1 to Q3 already follow it). Add questions for the
   PESP steps the demo needs: building facts, registered owner and contacts, deed history, conditions.
   Choose them by what the demo story needs, not by question number.
2. **Early to mid December:** pick the demo landlords (below). Build the graph skeleton with one real
   checkpoint (accept or reject a name-match lead) and a checkpointer. Run end to end, deterministic only.
3. **Late December:** holiday buffer. Light work: plain-language rendering of sections, "not yet covered"
   placeholders for steps without tools, report export.
4. **Early January:** add the narrative layer behind the firewall checks. Rehearse. Prebuild and save a
   backup run in case of a network or API problem during the talk.
5. **Freeze about a week before the talk.** No new features after that, only fixes found in rehearsal.

The conversational agent can appear at the end as a short "ask a follow-up" step. It is not on the critical
path.

## Choosing the demo landlords

- Candidates come from read-only probing of the graph, then a human review. Criteria: rich data across the
  steps that have tools; a mix of recorded findings and name-match leads that need a human decision; at
  least one step where the honest answer is "the graph cannot say".
- Prefer landlords already prominent in public reporting or enforcement. Avoid small or private owners.
  Show person names only with their recorded role.
- Consider asking JustFix or HDC for a landlord they would like to see. It guarantees relevance and gives
  them a way to check the output against what they know.
- Verify every number in the chosen reports by hand before the talk.

### Working choice (2026-11-24)

Found by read-only probing of the graph, then a web check for public recognition.

- **Main demo: the Yonatan Bahumi portfolio.** Publicly recognizable: he appeared on the Public Advocate's
  2025 Worst Landlords list (Bronx Times, 22 Jan 2025). Show that list as context only, never as a graph
  answer, and never as a court finding. In the graph: 55 lots, 176 residential units, 7 landlord records
  (six exact-name records joined by an identity cluster, plus one misspelled record, "BADHUMI", linked only
  by a shared address), 69 corporate names on building registrations (31 with an exact-name DOS match,
  which are leads), 354 deeds (239 with amount 0, which is not a free sale), 89 litigation cases, 1
  recorded harassment finding. The BADHUMI record is the planned checkpoint: accept or reject it, and the
  portfolio changes.
- **Contrast: the Moses Berkovics portfolio.** Many leads (about 30 name-match edges, 44 corporate names, 31
  with a DOS match), no recorded findings, low violations per unit according to a third-party aggregator
  (unverified). Shows "leads need a human" without an accusation. A similarly spelled name with a very
  different record exists; useful to illustrate why we never merge on similar names. Do not claim they are
  related.
- **Dropped:** Pinchasov, Westreich, Dushinsky (no public coverage found). Weinberger (too large).
  Ohebshalom: the press-covered owner and his alias are not in the graph under those names, so it cannot
  show alias handling.
- **Unverified before use:** the actual values of Violation `status` and `violationClass` (the counts
  above assumed `Open` and `C`); the borough breakdown, and whether the Public Advocate's 19 Bronx
  buildings are among the 55 lots; every number, by hand, before the talk. Portfolio and network IDs are
  run-local and must not appear on a slide.
- Show person names only with their recorded role.

## Why

We are building two different products, and a single 28-tool agent serves neither well:

1. **Conversational agent** (LangChain): manages a conversation and answers questions about buildings,
   landlords and portfolios.
2. **Report graph** (LangGraph, human in the loop): produces a landlord research report that follows the
   PESP guide's procedure.

The 28-tool agent costs a lot per call (every tool definition rides on every call) and makes tool choice
harder. The report is a fixed procedure, so it does not need a model to decide what to look up.

## Proposed shape

- **Shared question library** (`watchline/questions/` or similar): the competency questions as plain
  deterministic functions. Each returns a structured answer with evidence and caveats (the existing
  answer contract). They are not tools.
- **Product 2 (report graph):** wires the functions in as LangGraph nodes. No model calls except optional
  drafting and the web research step. Human checkpoints use `interrupt()` with a checkpointer.
- **Product 1 (agent):** a small set of grouped tools (about 6 to 8) built on the same functions, organised
  by what a person asks about:
  - a building or lot (address resolution, facts, owner contacts)
  - a landlord or owner
  - a portfolio or network
  - deeds and financing
  - conditions (violations, complaints, litigation)
  - address resolution (Geosupport), and web search later
- **Neo4j MCP** stays an optional, clearly labelled explorer, not the main path. Raw rows carry no caveats,
  no numbers guard and no answer contract, and free-form Cypher costs more calls on a graph with this many
  traps.
- **Open on product 1:** whether it needs Deep Agents at all (its built-in planning, file and subagent
  tools add tokens to every call) or a plain LangChain agent is enough.
- **Decide by bake-off, not argument:** run the small smoke set against (a) current tools, (b) MCP only,
  (c) grouped tools. Compare correctness and cost. See `docs/eval-agent-cost.md`.

## The PESP guide as a graph

The guide: Step 1 find the legal owner and mailing address in property records. Step 2 research the LLC
(registered agent, officers, addresses, related LLCs, web search). Step 3 bring it together as a table of
inferences with sources, and a strategic takeaway. Its five focus questions: who is my landlord; how many
properties and where; do they hold or sell; what are the conditions; is there news.

| # | Step | Guide equivalent | Graph source | Type |
|---|---|---|---|---|
| 1 | Resolve the address | Search by address | Geosupport, then lot and building | Deterministic. Human picks if ambiguous |
| 2 | Building facts | Units, value, year built, PIN | Lot fields (PLUTO) | Deterministic |
| 3 | Registered owner and contacts | Legal owner, mailing address | HPD registration contacts (owners, agents, officers) | Deterministic |
| 4 | Deed history | Sales history, hold versus sell | Deeds, grantees, grantors, recorded dates | Deterministic |
| 5 | Entity research | Registered agent, officers, process address | DOS entities matched to owner names | Deterministic. **Human reviews name matches** |
| 6 | Related entities | Similar LLCs, shared addresses | Landlord links by name, address, identity; mail-drop and masked flags | Deterministic. **Human accepts or rejects each link** |
| 7 | Portfolio | How many properties, where | Owner portfolio and operational network | Deterministic, shown as a lead |
| 8 | Building conditions | Organising leverage | Violations, complaints, litigation | Deterministic |
| 9 | Web research | Search names and addresses, news | Web search | LLM-assisted. **Human adds findings**. Lower confidence |
| 10 | Assemble | Step 3 inference-and-source table | All of the above | Deterministic, with a human-written takeaway |

## Human checkpoints

Where the guide says judgment is needed: whether two LLCs are related, spotting virtual-office or
mail-drop addresses (the curated mail-drop list helps), and writing the final inference. Each accept or
reject is recorded in the report.

## Principles to carry over

- Every inference in the report carries its source (the guide's Step 3 table). This is the answer contract
  with evidence and caveats.
- Three confidence levels, shown differently: a graph record, a lead the researcher accepted, a web source.
- Leads stay leads. The report never states common ownership as a finding unless the researcher records it
  as their own inference with sources.
- Avoid paid property sites (the guide's advice). Web research uses free, public sources and records them.

## Gaps and open questions

- The DOS data is New York entities only, and only those matching a graph owner or grantee name. Out-of-state
  parents (Delaware, Florida, hedge funds) fall to web search and the researcher.
- Financial standing and distress (the guide's sixth question) are out of its focus. Financing documents are
  in the graph, so this is a possible later section.
- Which of the 28 questions map to which node, and which remain for the agent only. Settle this when the
  demo question list is chosen.
- Report format and export (the guide uses a notes document and an inference table). Plain-language
  rendering for non-technical readers is now a requirement.
- How WoW and this report differ, so the demo can say it plainly. Check what Who Owns What shows today
  before claiming a difference.
- Reader: organizers and non-technical staff as well as data people (decided for the demo). Journalists
  later.
- Evals: the report graph's nodes are deterministic, so most of its tests are free (snapshot tests on
  sections). Only the web research and narrative steps need model-based checks, and the narrative firewall
  checks are deterministic too.
- Whether the demo's web research step is live or prerecorded. A live web step is a risk during a talk.
