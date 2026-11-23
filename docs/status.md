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

- Streamlit page (branch `streamlit-page`, plan in `docs/plans/streamlit-page.md`): `watchline/ui/` (`render.py`, `app.py`, `fixtures.py`), `make ui`,
  `?fixtures=1` previews every kind without the model. Generic renderer only; smoke tests in `tests/test_ui.py`. Logo in the sidebar (rounded, pulled up with CSS). Checked on live data by hand; merged.
  Two nested pulldowns in the sidebar (`watchline/ui/samples.py`: competency question, then its sample queries, Q1 and Q2 for now; a pick runs in the chat); not yet looked at in a browser.

- Q2 registered owner (branch `q2-registered-owner`, plan in `docs/plans/q2-registered-owner.md`, with live probe results):
  `watchline/registration/registration.py`, `registered_owners(client, graph, rg, text)`: every HPD registration per building of the
  addressed lot, with `lastRegistered` and `registrationEnd` (from the building-registration relationship) and the owner contacts as
  recorded. Agent wiring: `registered_owner` tool (`watchline/agent/tools.py`; the per-building list is `registration_buildings`, apart from
  the profile's `buildings`), `registration` kind and `registrations` section in `answer.py`, system-prompt lines, `build_agent(..., rg)`, and
  `connect()` now returns five values. Tests: 156 fast tests pass; 11 live tool-level evals (`tests/evals/q02_cases.yaml`, from live probes)
  pass with the live tests and the Q1 evals (`make test-live`, `make eval`). One UI fixture (`?fixtures=1`, `registration`); generic renderer.
  Agent-level Q2 evals written (`tests/evals/agent_q02_cases.yaml`, `tests/test_agent_eval_q02.py`: 10 cases and a judge calibration). First run of `make eval-agent` (2026-11-23, Haiku agent and judge, one run): Q1 11 of 11, Q2 8 of 10, both calibrations pass. The two Q2 failures were a prompt gap (the model cited the profile section `buildings` on a registration answer; the prompt now says to use `registrations`) and a rubric that asked the model to repeat a code-attached caveat (dropped); both cases pass on rerun. The other cases have not been rerun since the prompt change. Merged without: a full three-run eval rerun, a worst-case-lot timing check, `make chat` by hand on anchors A and D and an ended
  registration, and the fresh-context review (`/code-review`). Sidebar dropdown text color and the footer's pinning were not confirmed in a browser.

## Next
- Q2 follow-ups left from the merge: the review, a three-run `make eval-agent`, the `make chat` hand check, worst-case timing.
- Streamlit follow-ups: navy/gold brand banner, per-kind renderers and lead/finding pills (when a tool returns leads), streaming.
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
