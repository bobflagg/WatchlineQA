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

- Q3 deed grantee against HPD owner (branch `q3-deed-vs-owner`, plan in `docs/plans/q3-deed-vs-owner.md`; merged 2026-11-24 ahead of a change in direction):
  `watchline/deeds/` (`deed_vs_owner`, N1/N2/A1 comparison), `deed_vs_owner` tool, `ownership_comparison` kind with `deeds`, `owners` and `comparison`
  sections, system-prompt lines, UI fixture and Q3 samples. 217 fast tests, the live tests and 34 tool-level evals (`make eval`, 7 for Q3) pass.
  Agent-level Q3 evals are written (`tests/evals/agent_q03_cases.yaml`, `tests/test_agent_eval_q03.py`). The LLM judge is now off by default for
  all agent evals (cost); `make eval-agent JUDGE=1` adds it. First agent-level run (2026-11-23, Haiku agent, judge off, one run): 7 of 8 pass; `follow-up-from-a-profile` did not complete (Anthropic "credit balance too low" error, not an answer failure) and needs a rerun. Merged without: the `follow-up-from-a-profile` agent eval (rerun), a judge-graded run, `make chat` and `make ui` by hand, and the fresh-context review (`/code-review`). Agent-eval cost analysis: `docs/eval-agent-cost.md`.

- Eval cost: **resolved** (`docs/plans/eval-cost.md`). Cause: the Console showed 640M Haiku 5.5 tokens on 2026-11-23; Deep Agents sets `recursion_limit` 9,999 and the model repeated an identical `building_profile` call with nothing to stop it. Now: step limit 30 in `chat.py`, `RepeatGuardMiddleware` (`watchline/agent/repeat_guard.py`), and in evals a per-run spend cap, a per-case call limit and timeout, a usage log (`build/agent-eval/usage-*.json`) with cache writes priced by TTL, and a judge records cap. Stage 5 (agent only, judge off, 2026-11-24): **29 cases ran (pass/fail counts were not recorded), about $0.026 per run, 71 calls, 88% of input read from cache** (that run used cap $0.50, 8 calls per case; none reached it). `make eval-agent` sets only `EVAL_JUDGE=0` (opt in with `JUDGE=1` or `EVAL_JUDGE=1`); the spend caps come from the environment or `.env`, else the code defaults ($0.25, 12 calls per case). Keys: `EVAL_ANTHROPIC_API_KEY` for evals and `AGENT_ANTHROPIC_API_KEY` for chat, UI and notebooks, each in its own Anthropic workspace (template `.env.example`); the generic `ANTHROPIC_API_KEY` is no longer read. **Pending:** reconcile the logged cost with the Console for the eval key (20% rule; only runs on the new key count, about $0.04 in total today). Price table: `watchline/evals/pricing.py`.
- Known issue, repeated lookups: after a correct profile lookup the model sometimes emits the identical tool call again (first seen on 5413 7 Avenue, the Q3 `follow-up-from-a-profile` case, which ran unbounded before the guard). The guard answers the repeat with a fixed message and the model then writes its answer, so each affected case costs one extra model call. In the Stage 5 run it fired once in each `follow-up-from-a-profile` case (Q2: 224 54 Street; Q3: 5413 7 Avenue) and not in `follow-up-same-thread` (two distinct addresses). Regression evals: those two cases, plus the `tests/test_eval_guard.py` repeat-guard tests with the fake model. **Open question:** why this happens on the profile-first turn of the follow-up cases and not in the Q1 profile cases (same tool, same prompt); not diagnosed.

## Next
- Q2/Q3 review done 2026-11-24 (`/code-review` high on both merges; fixes in `6b9964c`): owners cap caveat, `owners_from_all_registrations` caveat, absence evidence needs a lot that was read, ACRIS source on no-deed; eval Makefile and harness fixes. `make ui` checked by hand (looks fine). `make chat` checked by hand 2026-11-24 on anchors A and G and an ended registration, all good. Q3 `follow-up-from-a-profile` rerun passed (judge off, cap $0.10, 5 calls, about $0.002; the repeat guard still fires once).
- Agent evals, 2026-11-24 (judge off, about $0.025 a run): three runs gave 26, 25 and 27 of 29 passed (failure names were not kept); a fourth with the full log gave 28 of 29. The one failure there was a checker false positive from my review cleanup (the body-text hedge no longer excused "not confirmation that they are the same party"); fixed by letting "confirm" count only before that/whether/to be, with a unit test. The earlier failures were probably the same cause, but that is not confirmed; rerun `make eval-agent` once to check. Worst-case timing: a 237-building lot's registrations 0.05 s, a many-deed lot's deed comparison 0.04 s.
- Left from Q2/Q3: reconcile the eval cost with the Console; one more `make eval-agent` run to confirm the checker fix.
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
- Architecture: two products (conversational agent, human-in-the-loop report graph following the PESP guide) on a shared
  question library. Proposal in `docs/plans/report-graph.md`; decide after the eval-cost work and a small bake-off.
- Web chat after the terminal one: when?
- Which competency questions come first after the building profile.

## Not yet done
- Hooks (the deny rules cover reads and edits, but commit-time checks are not enforced).
- `make doctor` (checks Neo4j and the sidecar), `make explainer`, `make chat`.
- Decide what to do with `specs/` (a symlink to another project; currently untracked).
