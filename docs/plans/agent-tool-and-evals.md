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

## Review follow-up (fresh-context review of c5f9f34)

Fixed:
- Any exception becomes `status: error` (catch-all; `ReleaseMismatch`, bad rows, serialization). `invalid_input` can only come from
  address resolution. An unavailable Geosupport is `status: error`, not `ok`.
- `lot_totals` renamed `totals_across_all_listed_buildings`; the cap caveat says the totals cover all buildings and will not
  equal the rows shown; `buildings_listed_is_lower_bound` flags the graph's 200-row read limit.
- `harassment_findings` renamed `harassment_findings_after_inquest_or_trial`, so a bare 0 cannot read as "no harassment".
- `zip_code` accepts an integer; the description now covers each status and neighborhoods.
- `check_ontology` is real: totals must equal the same-group sums of the building rows, every count row has a class or type key,
  lot-wide keys appear only under `lot`, counts name unit and source. Unit tests prove it rejects each violation.
- New cases: year built, class and assessed value (D, A); typing 218 and 220 (ZIP only, integer ZIP); inferred
  "Fifty-fourth"; a building with harassment findings (also checked against a direct graph count); at least two ambiguous candidates.

Not done:
- Matching caveats by prose substring is still brittle (nit). Fixing it needs structured caveat codes in `profile.py`; do that
  when the agent-level evals need them.
- `q01.md` (a symlink to another project, not edited here) says anchor D is a variant; live Geosupport returns exact for
  "224 54 Street" and variant only for spellings like "224 54th St". The eval records the live behaviour.
- No outage case against the live services (it would need the sidecar stopped); covered by unit tests instead.
