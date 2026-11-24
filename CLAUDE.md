# WatchlineQA

Accountability AI assistant for NYC rental housing: a chat agent (LangChain Deep Agents) that answers
questions from the Watchline Neo4j knowledge graph, with web search for outside context. Users:
journalists, tenant advocates, watchdog agencies, the public. See `docs/process.md` for how we work.

## Stack and commands

- Python 3.13, managed with uv. Everything runs through `make` (run `make help`): `make check` before
  committing, `make test` (fast), `make test-live` (needs Neo4j and the sidecar), `make sidecar`.
- Neo4j: `neo4j://localhost:7687`, database `watchline`. Credentials are in `.env`; do not read or print it.
- Geosupport sidecar (Docker, see `geosupport/README.md`) resolves typed addresses to BBL and BIN.
- Dev-time Neo4j exploration uses the `neo4j-watchline` MCP server (`.mcp.json`, read-only).

## Layout

- `watchline/geosupport/`: address resolution (Q1.3). Geosupport decides the outcome; the graph only says
  whether the lot is held and which lots share the BIN.
- `geosupport/`: the Docker sidecar (pass-through only; interpretation stays in `watchline/`).
- `specs/questions/`: competency questions (a symlink to another project; read the files you need and do
  not browse the source project).
- `docs/`: process, plans, explainers.
- `docs/ontology.ttl`: the ontology the graph is based on. Source of truth for the ontology rules below.

## Agent-building skills

The `langchain-skills` plugin is installed at project scope (`.claude/settings.json`). Before writing any
LangChain, LangGraph or Deep Agents code, load `langchain-skills:langchain-build-agent`; for evals also
`langchain-skills:langchain-eval-engineering` and `langchain-agent-experiments`. Check
`~/.claude/plugins/marketplaces/langchain-skills/skills/` if a name fails. These help Claude Code write the
agent. They are separate from the skills the agent itself loads at run time (the ontology rules).

Before writing or changing any Cypher, load `neo4j-cypher-skill` (Cypher 25; our Neo4j is 2026.04, which
supports Cypher 5 and 25). Check labels and properties against the live graph first, and use EXPLAIN on any
new query. The agent's graph tools stay read-only.

## UI skills

For any Streamlit work, load `developing-with-streamlit` (API details, once Streamlit is a dependency) and
`watchline-ui` (look, layout, and how answers, leads and caveats are displayed). UI code lives in
`watchline/ui/`, apart from agent and graph code, and renders the structured answer contract.

After a fresh clone, run `uv sync && uv run streamlit skills` to link the Streamlit skill. It points into
`.venv`, so it is git-ignored.

## Ontology rules (apply to every answer)

One source, shared with the agent's system prompt (`watchline/agent/prompts/ontology_rules.md`). Edit the rules
there, not here:

@watchline/agent/prompts/ontology_rules.md

## Graph vs ontology naming

The graph label is `Lot` (ontology: TaxLot). Some properties are shorter: `unitsRes`, `assessedTotal`,
`plutoNumBuildings`, Document `docType`, `docDate`, `amount`, Landlord `name`. `HAS_PARTY` carries
`partyType`; `CONNECTED_BY_*` carry `weight` and group/edge ids; `CONNECTED_BY_IDENTITY` also carries
`stage` and `evidenceType`. Check the live graph before writing a query.

## Conventions

- Graph tools are read-only, parameterized, row-limited, with timeouts, and return evidence plus caveats.
- Every answer is structured data, not free text: a summary, the facts with their evidence, the caveats that
  apply (lead vs. finding), the sources, and a `kind` tag (for example profile, list, comparison, network)
  that tells a renderer what shape it is getting. Caveats are fields, so no display can drop them. Each
  answer also has a plain-markdown rendering so the terminal chat works. Layout and styling wait for the UI.
- No free-form Cypher from the model in the main path.
- Live model calls cost money. Never run live agent evals, notebooks or chat loops unless `EVAL_MAX_USD` (or the
  equivalent cap) is set. State the maximum cost before any live run, run no more cases than were approved, and
  prefer the scripted fake model for anything that tests our code rather than the model. Evals use the eval
  API key, the agent and notebooks use the agent key.
- Write the simplest thing that passes the tests and answers the question. Small commits.
- If Claude makes the same mistake twice, add a line to "Mistakes to avoid" below.

## Mistakes to avoid

- Do not guess expected values for evals or tests (an address's lot, outcome or shared BIN). Probe the live
  graph and Geosupport first, then write the expectation.
