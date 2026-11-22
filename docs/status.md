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
  Not yet: fresh-context review, explainer, merge. Unregistered-lot live test still to add.

## Next
- Review the building-profile diff in a fresh context, then merge.
- Wrap `building_profile` as an agent tool (read-only, row-limited) and add the first eval cases from Q1.

## Decisions
- Agent built with LangChain Deep Agents. Runtime graph access uses the Python driver with curated,
  read-only tools. The Neo4j MCP server is for development only.
- Web search comes after the graph side is solid; its results are context, never identity evidence.
- Understanding step: explainer docs only (no quizzes or micro-worlds). Specs in `docs/understanding/`,
  rendered pages published as artifacts.

## Open questions
- Which Claude model the agent should use.
- Terminal interface first, web chat later?
- Which competency questions come first after the building profile.

## Not yet done
- Hooks (the deny rules cover reads and edits, but commit-time checks are not enforced).
- `make doctor` (checks Neo4j and the sidecar), `make explainer`, `make chat`.
- Decide what to do with `specs/` (a symlink to another project; currently untracked).
