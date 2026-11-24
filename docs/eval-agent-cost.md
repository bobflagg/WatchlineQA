# Cost of `make eval-agent` (analysis, 2026-11-23)

Method: read the eval code (`tests/test_agent_eval_q0{1,2,3}.py`, `watchline/agent/chat.py`), the saved results in
`build/agent-eval/*.json`, and measured sizes with direct tool calls (no model, no evals). Model-call counts are derived from the
code, not measured: the saved traces record tool calls but not model calls.

## Invocations of the agent per run

| | cases | user turns |
|---|---|---|
| Q1 | 11 | 12 (one follow-up case) |
| Q2 | 10 | 11 (one follow-up case) |
| Q3 | 8 | 9 (one follow-up case) |
| Total | 29 | **32** |

- Repeats: there is no repeat loop. "Three runs" means running `make eval-agent` three times by hand, so the multiplier is 3.
- Retries: `ask()` (`watchline/agent/chat.py`) re-invokes the agent once only when the numbers guard flags a number that is not in the tool
  results. None of the saved runs has a corrected case, so the expected number of retries is 0.
- Per run: 32 x 1 = **32** invocations, at most 32 x 2 = 64 if every turn were corrected.
- Three runs: 3 x 32 = **96**, worst case 192.
- The judge is separate from the agent and is off by default (`EVAL_JUDGE=1` turns it on). With it on: about 41 rubric calls
  (15 + 16 + 10) plus about 24 calibration calls, roughly 65 judge calls per run.

## Model calls per invocation (estimate)

A turn that calls one tool takes about 2 model calls: one to pick the tool, one to return the structured answer (`ModelAnswer`).

| Turn type | Model calls |
|---|---|
| One tool call | about 2 |
| Follow-up with no tool call (Q1) | 1 |
| Q2 follow-up (two tool calls) | 2 to 3 |
| Q3 multi-lot case (three tool calls) | 2 to 4 |

Tool calls in the saved runs: Q1 11 across 12 turns, Q2 11 across 11 turns, Q3 9 across the 7 cases recorded (the eighth did not finish).

- Per run: roughly **62 to 70** model calls.
- Three runs: roughly **190 to 210**.
- Not known: whether several tool calls in one turn run in parallel or in sequence.

## Input size

| Part | Size |
|---|---|
| System prompt (`system.md` with the ontology rules) | 10.6k chars (1,785 words, about 2.7k tokens) |
| Deep Agents base prompt | about 2.3k chars |
| Tool descriptions (`building_profile`, `registered_owner`, `deed_vs_owner`) | 0.8k, 1.1k, 1.2k chars |
| Tool argument schemas | 0.56k chars each |
| `ModelAnswer` schema | 2.5k chars |
| Fixed input on every model call | about 20k chars, about 5k tokens |

Tool results are added on the second call of a turn:

| Tool | Typical size | Largest measured |
|---|---|---|
| `building_profile` | 2.3k to 4.9k chars | 4.9k (5413 7 Avenue) |
| `registered_owner` | 1.3k to 1.9k chars | 1.9k |
| `deed_vs_owner` | 0.9k to 9.8k chars | 15.4k (102 West 57 Street, about 4k tokens) |

The `deed_vs_owner` output is capped at 10 deeds and 100 comparison pairs, which bounds it at a few tens of thousands of characters. The
worst-case profile lot (16,771 problems) was not measured; its profile is grouped by class and capped at 25 buildings, so it should
stay in the same range.

## What drives the cost

Most of the cost is the fixed prompt and schema (about 5k tokens) re-sent on about 65 calls per run, not the tool results. Trimming
the system prompt or the tool descriptions would save more than trimming results. The judge is the other large item when enabled.
