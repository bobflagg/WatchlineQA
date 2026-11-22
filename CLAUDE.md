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
LangChain, LangGraph or Deep Agents code, load `langchain-skills:ecosystem-primer`, then the specific skill
(`deep-agents-core`, `deep-agents-orchestration`, `deep-agents-memory`). These help Claude Code write the
agent. They are separate from the skills the agent itself loads at run time (the ontology rules).

## Ontology rules (apply to every answer)

- Ownership links are **leads, not findings**: operational networks, owner portfolios, landlord-to-landlord
  links, name and address matches, DOS entity matches. Say "lead" and show the evidence.
- A deed shows ownership, not shared operation. A deed amount of 0 is common and is not a free sale.
- Never merge identities: HPD contacts, deed grantees and grantors, document parties and DOS entities are
  separate. Compare names at answer time; names are as recorded, never normalized in the graph.
- Violations, complaint problems and litigation are what was cited, reported or brought, not findings of
  fault. Count by class or type; never sum into a severity score. Only "After Inquest" or "After Trial" is
  a harassment finding.
- Most recent deed uses `recordedDate`, not `documentDate`.
- Lot-wide values (units, assessed value) belong to the lot, never a building. Violations, problems and
  litigation belong to buildings, and exist only for HPD-registered lots and buildings.
- Network and portfolio ids are run-local. Masked and mail-drop addresses are method decisions or
  unreviewed leads, not findings about the address or its users.
- Person names: show only with the role they were recorded in.

## Graph vs ontology naming

The graph label is `Lot` (ontology: TaxLot). Some properties are shorter: `unitsRes`, `assessedTotal`,
`plutoNumBuildings`, Document `docType`, `docDate`, `amount`, Landlord `name`. `HAS_PARTY` carries
`partyType`; `CONNECTED_BY_*` carry `weight` and group/edge ids; `CONNECTED_BY_IDENTITY` also carries
`stage` and `evidenceType`. Check the live graph before writing a query.

## Conventions

- Graph tools are read-only, parameterized, row-limited, with timeouts, and return evidence plus caveats.
- No free-form Cypher from the model in the main path.
- Write the simplest thing that passes the tests and answers the question. Small commits.
- If Claude makes the same mistake twice, add a line to "Mistakes to avoid" below.

## Mistakes to avoid

- (none yet)
