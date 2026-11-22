# Slice: building profile as an agent tool, plus first Q1 evals

Approved plan, as built. Branch `agent-tool-q1-evals`.

## Decisions
- Agent model default is `claude-haiku-5-5` (`watchline/agent/config.py`, override with `AGENT_MODEL`). Cheapest, and the
  likeliest to drop caveats; agent-level evals in the next slice measure that.
- Evals are tool-level only: deterministic, no LLM, no API key.
- Only `langchain` was added (for `@tool`). `deepagents` comes with the agent wiring.

## Built
- `watchline/agent/tools.py`: `profile_to_dict` (JSON-safe, counts by type, buildings capped at 25 with the addressed one
  first) and `make_building_profile_tool` (`building_profile(address, borough, zip_code)`). Failures are answers:
  `needs_borough`, `invalid_input`, `error` (outage, never "not found"). Read-only, row-limited and timed out at the graph.
- `tests/evals/q01_cases.yaml` + `tests/test_eval_q01.py`: 11 cases (multi-building, variant, single building, PLUTO vs HPD
  counts, unregistered lot, ambiguous, two not-found, no borough, not an address, shared-BIN lots). Every case also checks
  that nothing is summed into a total or score, that lot-wide values stay off buildings, and that counts name unit and source.
- `make eval` runs just the evals; `make test-live` includes them.
- Output size: anchor D about 0.9k tokens, anchor A about 1.1k.

## Findings
- CLAUDE.md named skills that are not in the installed plugin (`ecosystem-primer`, `deep-agents-*`); corrected to
  `langchain-build-agent` (plus the eval skills).
- Two eval expectations were guessed wrong first (224 54 Street resolves exact, not variant; 32-19 55th Street is not the
  shared-BIN lot). Both fixed from live probes; added to "Mistakes to avoid".

## Not in this slice
`create_deep_agent`, system prompt, ontology skills, agent-level (LLM-judged) evals, chat UI, web search.
