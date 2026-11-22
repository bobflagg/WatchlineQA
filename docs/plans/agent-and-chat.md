# Slice: the Deep Agent, a terminal chat, and agent-level Q1 evals

Approved plan, as built. Branch `agent-and-chat`.

## Decisions
- Agent model `claude-haiku-5-5` (`AGENT_MODEL`); judge model `claude-haiku-5-5` (`JUDGE_MODEL`). Both are env vars.
- Ontology rules live in one file, `watchline/agent/prompts/ontology_rules.md`. The agent's system prompt fills them in;
  `CLAUDE.md` imports the same file with `@`. "Graph vs ontology naming" stays in CLAUDE.md (notes for writing Cypher, not rules
  for answers).
- Terminal chat first (`make chat`). Rules are in the system prompt, not a skill, so the model cannot skip them.
- Model-calling tests carry the `llm` marker. `make test`, `make test-live` and `make check` never call a model;
  `make eval-agent` does.

## Built
- `watchline/agent/agent.py`: `build_agent(client, graph, pg, model=, checkpointer=)` over `create_deep_agent`.
  Deep Agents offers file, shell and subagent tools by default. A harness profile registered under the `anthropic` provider
  excludes them (the model is offered only `building_profile`), the general-purpose subagent is disabled, and reads and writes
  are denied as a second layer. The backend is the in-memory default, so no repo file is reachable.
- `watchline/agent/chat.py`: `ask()` (one turn: answer, tool calls, tool results) shared by the chat and the evals; a REPL
  that prints each tool call as it happens.
- `watchline/agent/prompts/system.md`: role, how to read each tool status, the shape of a profile answer, the rules.
- Tests: `tests/test_agent.py` drives the real graph with a scripted model (no key): tools offered, system prompt received,
  tool result reaches the model, needs_borough flows back, a removed built-in cannot run, follow-ups keep the thread.
  Mutation check: with the lockdown patched out, the model is offered nine tools and the test fails.
- `tests/test_agent_eval_q01.py` + `tests/evals/agent_q01_cases.yaml`: 10 cases (multi-building, two counts, unregistered lot,
  variant, ambiguous, no borough, not found, harassment finding, slumlord trap, follow-up). Deterministic checks first (tool
  called, regexes), then the judge grades rubric items. Plus a judge calibration test: four clearly bad answers must all FAIL.
  Results of each run are written to `build/agent-eval/<timestamp>.json`.

## Results (Haiku 5.5 agent, Haiku 5.5 judge, 2026-11-22)

| Run | Result |
| --- | --- |
| 1 | 10 of 10 cases pass |
| 2 | 10 of 10 cases pass, judge calibration passes |
| 3 | 10 of 10 cases pass, judge calibration passes |

Two earlier runs failed for harness reasons, not model reasons, and are not counted:
- The judge call used `temperature`, which this model rejects (HTTP 400).
- The judge spends tokens on a thinking block; at `max_tokens=300` it sometimes ran out before writing a verdict, and the harness
  read the empty reply as FAIL. The budget is now 2000 and an empty reply raises a harness error instead of counting as a verdict.
- A regex flagged "this does not mean the lot has no buildings" as a claim that the lot has no buildings. Added `must_not_assert`,
  which ignores negated sentences (unit-tested).

## Findings
- Haiku relays the caveats well with this prompt: it names the addressed building, gives both building counts by source, keeps
  units lot-wide, says "no building recorded in the HPD registrations", declines to call anyone a slumlord, and treats
  "Tenant Action/Harrassment" as what was brought, not a finding.
- The judge is the same model as the agent. Calibration shows it rejects clear violations, but subtle ones could still pass; raise
  `JUDGE_MODEL` before trusting a high pass rate on harder cases.
- `register_harness_profile` is a process-wide registry and merges with earlier registrations, so a "no lockdown" check must run in a
  fresh process.
- Only three runs of ten cases: this shows the prompt works on these cases, not a stable rate. Add cases as questions are added.

## Not in this slice
Web search, more tools and competency questions, a web UI, deployment, tracing, Deep Agents skills, cross-session memory, explainers.
Caveat codes (so evals need not match prose) are still undone.
