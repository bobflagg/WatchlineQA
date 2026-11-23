# Structured answers (branch `structured-answers`)

## Why
Free-text answers let the model drop or reword a caveat and add counts into numbers the records never gave ("25 rows", which was also
wrong). `CLAUDE.md` now says every answer is structured data with a markdown rendering. This slice builds that contract for the one tool
we have.

## What was built
- `watchline/agent/answer.py`: `ModelAnswer` (what the model fills: `kind`, `summary`, `facts` with evidence references), `Answer` (what
  code builds), `assemble`, `render_markdown`, `ungrounded_numbers`.
  - Kinds: `profile`, `clarification`, `not_found`, `refusal`, `error`. More (list, comparison, network) arrive with the tools that need them.
  - Evidence references point at a section of the tool result (`lookup`, `resolution`, `characteristics`, `counts`, `buildings` with or
    without a BIN, `totals`). Code copies the tool's own data in; a reference to nothing is kept as `unresolved`.
  - Caveats and sources are attached by code from every tool result the answer rests on, verbatim, de-duplicated. A follow-up can cite an
    earlier lookup in the thread; the caveats of a cited earlier result come along.
- Caveats have stable codes (`Caveat(code, text)`, `CaveatTemplate`); the tool emits `caveats: [{code, text}]` and `sources`. An `error`
  result carries a `lookup_failed` caveat.
- `build_agent` passes `response_format=ToolStrategy(ModelAnswer)`; `chat.ask` assembles the `Answer` and `Turn.answer` is its markdown.
  `Turn.structured` is the object, `Turn.model_text` is only what the model wrote. `memory_checkpointer()` allows the answer types in the
  LangGraph store (otherwise it warns that it will block them).
- `chat.ask` checks the model's text for numbers that are in neither the tool results nor the user's messages. If there are any, the model is
  asked once to answer again (`Turn.corrected` lists them). A reply with no structure prints a notice that no caveats are attached.

## Decisions made on evidence
- **ToolStrategy, not ProviderStrategy.** Native structured output let the model end its turn with JSON saying "let me look that up"
  without calling the tool (1 of 10 on `224 54th St, Brooklyn`; the tool strategy missed 0 of 12). The tool strategy makes the final answer
  a tool call, so a prose promise cannot end the turn. Samples are small; the eval deterministic check (`tool` must be called) would catch it.
- **A numbers guard, not a "sum check".** A model-added sum cannot be detected as a sum, but it is a number the records do not contain.
  The first agent runs showed "25 complaints" (real sum 24), "6 problem rows" for six categories (real 10) and "8 complaint problems"
  (real 10). The guard flags each. It cannot catch a wrong number that equals some recorded number; the judge is the other guard.
- **Retry once.** Across three runs the guard fired on 5 of 36 case-runs (the model kept adding the problem rows of 224 54 Street). Failing
  in evals alone would leave users with the wrong number, so `ask` asks once for a corrected answer and records it.

## Eval changes
- Cases carry `kind` and `caveat_codes`. Caveat-relay rubric items are gone (code guarantees them). Regexes and the judge read only
  `model_text`, because caveat text legitimately contains phrases such as "not a statement that the lot has no buildings".
- Checks on every answer: a structured answer exists; every fact has evidence that resolves; no ungrounded number.
- New `sum-trap` case ("how many complaints"); `must_not_assert` for the unregistered lot now targets "has/have/with/there is no
  buildings|violations|complaints|litigation", not the allowed "no violations can be read" / "none are recorded".
- The harassment rubric item no longer demands the word "brought"; it asks that the model not describe `Tenant Action/Harrassment`
  cases as findings (judge strictness, run 2).
- Judge calibration: five bad and five good answers, rubric text loaded from the YAML; the slumlord good answer needed concrete figures
  and the judge is shown matching records.

## Results (Haiku 5.5 agent and judge, 2026-11-22)
| Run | Result |
| --- | --- |
| ToolStrategy, before the numbers retry | 11 of 12 (d-multi-building: ungrounded "8") |
| 1 | 12 of 12; retry fired on d-multi-building (10, 6) and variant-spelling (10) |
| 2 | 11 of 12; harassment rubric (judge wanted the word "brought"), then relaxed |
| 3 | 12 of 12; retry fired on d-multi-building (10) and slumlord-trap (10) |
Earlier failures worth keeping: the unregistered-lot answer said "no violations, complaint problems or litigation to report" (the
forbidden claim in other words), fixed in the prompt with the exact phrasing to avoid; the model once answered a clarification fact with
evidence of a section the tool never returned, which added the `lookup` section.

## Still open
- The model sums on its own about one answer in seven for this lot. The retry fixes the answer, not the habit.
- The judge is the same model as the agent. Three runs of twelve cases are a sanity check, not a rate.
- The Streamlit page and per-kind renderers wait for the web UI.
