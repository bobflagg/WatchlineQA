# Status

Read this first in a fresh session. Update it at the end of every slice.

## Done
- Address resolution (Q1.3): `watchline/geosupport/`, with unit tests and live tests passing.
- Geosupport sidecar (Docker), Makefile (`make help`), ruff config, `make check` passing.
- Process (`docs/process.md`), `CLAUDE.md`, ontology (`docs/ontology.ttl`).
- Skills installed: pipeline-explainer, neo4j-cypher-skill, langchain-skills plugin.
- Permission deny rules for `.env`, `ignore-this-directory/` and the ontology (`.claude/settings.json`).

- Building profile (branch `building-profile`, plan in `docs/plans/building-profile.md`):
  `watchline/profile/profile.py`, `building_profile(client, graph, pg, text)`. Unit and live tests pass
  (anchors D, A, 17 Battery Place). Worst-case building (16,771 problems) answers in about 0.5 s.
  Fresh-context review done and its findings fixed (see the plan). Not yet: explainer, merge.

- Agent tool and first Q1 evals (branch `agent-tool-q1-evals`, plan in `docs/plans/agent-tool-and-evals.md`):
  `watchline/agent/tools.py`, 16 tool-level eval cases (`make eval`). Reviewed, findings fixed, merged.
- Notebook for the tool: `docs/notebooks/building-profile-tool.ipynb`, `make notebook` / `make notebook-check`.

- Agent and chat (branch `agent-and-chat`, plan in `docs/plans/agent-and-chat.md`): Deep Agent with `building_profile`, system
  prompt with the ontology rules (one source: `watchline/agent/prompts/ontology_rules.md`, imported by CLAUDE.md), `make chat`, and
  10 agent-level evals (`make eval-agent`; 10 of 10 on three runs, Haiku agent and judge). Reviewed and fixed; merged.

- Agent notebook: `docs/notebooks/watchline-agent-chat.ipynb` drives the chat's functions through ten scenarios (merged).

- Structured answers (branch `structured-answers`, plan in `docs/plans/structured-answers.md`): `watchline/agent/answer.py` (kind, summary,
  facts with evidence; code attaches caveats and sources), caveat codes, a numbers guard with one retry, 12 agent evals incl. `sum-trap`.
  Reviewed, fixed, merged; both notebooks re-executed. Next evals to add: more kinds as tools arrive; a stronger judge model.

## Next
- Explainers for components with real flow (address resolution and profile pipeline, then the agent flow); `main` is pushed so code pins resolve.
- Pick the next competency question and its tool.

## Decisions
- Agent model: `claude-haiku-5-5` by default (env var `AGENT_MODEL`); revisit after agent-level evals.
- Evals start at tool level (deterministic); agent-level evals come with the agent.
- Agent built with LangChain Deep Agents. Runtime graph access uses the Python driver with curated,
  read-only tools. The Neo4j MCP server is for development only.
- Web search comes after the graph side is solid; its results are context, never identity evidence.
- Understanding step: explainers for components with real flow, a notebook per simple tool (`docs/notebooks/`); no quizzes or micro-worlds. Specs in `docs/understanding/`,
  rendered pages published as artifacts.

- Answers use a structured contract (summary, facts with evidence, caveats, sources, `kind`) with a
  markdown fallback. A bare-bones Streamlit page comes after the first slice or two, to test the contract
  against real data. Polished per-kind renderers wait for the UI.

## Open questions
- Web chat after the terminal one: when?
- Which competency questions come first after the building profile.

## Not yet done
- Hooks (the deny rules cover reads and edits, but commit-time checks are not enforced).
- `make doctor` (checks Neo4j and the sidecar), `make explainer`, `make chat`.
- Decide what to do with `specs/` (a symlink to another project; currently untracked).
