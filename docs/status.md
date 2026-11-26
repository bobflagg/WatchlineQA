# Status

Read this first in a fresh session. One line per feature; details are in the plan it links. The old long log is `docs/history.md`
(archive, not read in feature sessions). Update this file with `/wrap`.

## Done
- Address resolution (Q1.3): `watchline/geosupport/`, Geosupport sidecar, Makefile, ruff, `make check`.
- Process, `CLAUDE.md`, ontology (`docs/ontology.ttl`), deny rules for `.env` and the ontology.
- Building profile (Q1): `watchline/profile/`. Plan: `docs/plans/building-profile.md`.
- Agent tool and Q1 tool-level evals: `docs/plans/agent-tool-and-evals.md`.
- Agent and chat (Deep Agent, ontology rules in the prompt, `make chat`, agent evals): `docs/plans/agent-and-chat.md`.
- Structured answers (kind, summary, facts with evidence, code-attached caveats, numbers guard): `docs/plans/structured-answers.md`.
- Streamlit page (`watchline/ui/`, `make ui`, `?fixtures=1`): `docs/plans/streamlit-page.md`.
- Q2 registered owner: `docs/plans/q2-registered-owner.md`.
- Q3 deed grantee against HPD owner: `docs/plans/q3-deed-vs-owner.md`.
- Eval cost (spend caps, step limit, repeat guard, usage log; separate eval and agent keys): `docs/plans/eval-cost.md`, `docs/eval-agent-cost.md`.
- Demo slices: Q4 contacts, Q12.1 deed timeline, Q15 open violations, Q28 litigation, with agent evals: `docs/plans/demo-slices.md`.
- Identity checkpoint (links, decisions, portfolio effect): `docs/plans/identity-checkpoint.md`.
- Report graph, templated sections, Markdown export, `make report`, report page, one app navigation with chat and report,
  sample questions and address pulldown; browser walkthrough done; two verified backup runs:
  `docs/plans/report-graph.md`, `report-graph-build.md`, `report-demo-verification.md`.
- Q5 entity research (DOS records as leads, owner-entity report section): commit `5cefaac`.
- Who Owns What comparison (what WoW shows, where it matches, two findings): `docs/plans/wow-comparison.md`.
- Status and backlog reconciled with `git log` (F00): old status archived in `docs/history.md`; backlog in `docs/backlog.md` (no plan file; docs only).
- Reviews: `/code-review` done on Q2 and Q3 (fixes `6b9964c`) and on the slices.

## Next
Ready entries in `docs/backlog.md`: F01 graph schema check. Needs-you, blocked and later entries are not started.
Not covered by a section yet: web research (F17), complaints Q27 (F04), pest violations Q15.3 (F05). The narrative layer
(F10) comes after, in early January.

## Decisions
- Agent model: `claude-haiku-5-5` by default (env `AGENT_MODEL`); evals start at tool level, agent-level evals use the fake model where they test our code.
- Agent built with LangChain Deep Agents; runtime graph access uses the Python driver with curated, read-only tools. The Neo4j MCP server is for development only.
- Answers use a structured contract (summary, facts with evidence, caveats, sources, `kind`) with a markdown fallback.
- Web search comes after the graph side is solid; its results are context, never identity evidence.
- Two products on a shared question library: the conversational agent and the report graph (no model called by the report). `docs/plans/report-graph.md`.
- Understanding step: explainers for components with real flow, a notebook per simple tool; no quizzes.

## Open questions
- The graph snapshot is incomplete and will be rebuilt from Open Data before the January demo; pinned numbers are provisional (F08, F09, F02).
- Why the model repeats an identical tool call on the profile-first turn of follow-up cases (F13); the repeat guard handles it.
- Eval cost Console reconciliation for 2026-11-24 (F14).
- Web chat after the terminal one: when?
- The `specs/` symlink: keep untracked, track, or copy (F16).
