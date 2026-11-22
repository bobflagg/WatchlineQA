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
- Notebook for the tool (branch `tool-notebook`): `docs/notebooks/building-profile-tool.ipynb`, `make notebook` / `make notebook-check`.

## Next
- Explainers for components with real flow (address resolution and profile pipeline, then the agent flow); `main` is pushed so code pins resolve.
- Wire the Deep Agent (`create_deep_agent`, haiku default), system prompt and ontology skills; add agent-level evals that
  check the model relays caveats and never says "the lot has N buildings".

## Decisions
- Agent model: `claude-haiku-5-5` by default (env var `AGENT_MODEL`); revisit after agent-level evals.
- Evals start at tool level (deterministic); agent-level evals come with the agent.
- Agent built with LangChain Deep Agents. Runtime graph access uses the Python driver with curated,
  read-only tools. The Neo4j MCP server is for development only.
- Web search comes after the graph side is solid; its results are context, never identity evidence.
- Understanding step: explainers for components with real flow, a notebook per simple tool (`docs/notebooks/`); no quizzes or micro-worlds. Specs in `docs/understanding/`,
  rendered pages published as artifacts.

## Open questions
- Terminal interface first, web chat later?
- Which competency questions come first after the building profile.

## Not yet done
- Hooks (the deny rules cover reads and edits, but commit-time checks are not enforced).
- `make doctor` (checks Neo4j and the sidecar), `make explainer`, `make chat`.
- Decide what to do with `specs/` (a symlink to another project; currently untracked).
