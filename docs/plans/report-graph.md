# Report graph and product split (DRAFT proposal, 2026-11-24)

Status: proposal for discussion. Nothing here is built or decided. Source for the report procedure: the PESP
"How to Research Your Landlord" guide (May 2026, Strategic Landlord Research Guide).

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
- Which of the 28 questions map to which node, and which remain for the agent only.
- Report format and export (the guide uses a notes document and an inference table).
- Who the report's reader is: tenant organizers, journalists, or both.
- Evals: the report graph's nodes are deterministic, so most of its tests are free. Only the web research and
  drafting steps need model-based checks.
