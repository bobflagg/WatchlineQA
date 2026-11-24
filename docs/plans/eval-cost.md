# Eval cost plan: `make eval-agent` under $1 per merge check, under $5 per full run

(On approval this becomes `docs/plans/eval-cost.md`; plan mode blocks writing it now. Stage 0 used no model calls and did not read `.env`.)

## Stage 0 findings (code and docs only)

**The headline: the spend is not explained by the eval design as written.** Haiku 5.5 costs $0.10 per million input tokens, $0.50 output, $0.01 cache read, $0.125 cache write (5 min), and 5x those for prompts over 100k tokens (Anthropic pricing page, fetched 2026-11-24). One full run is about 65 agent calls at about 6-8k input tokens each, which is roughly 0.5M input tokens and 30k output: **about $0.06 for the agent, $0.03 to $0.05 more with the judge**. The 14 result files from 2026-11-23 imply roughly $1 in total. $35 is 30 to 70 times that. So either (a) something ran away, (b) the key ran a pricier model than the one recorded, or (c) other things used the same key. The first is the best-supported:

| Suspect | Evidence | Verdict |
|---|---|---|
| Runaway agent loop | `create_deep_agent` sets `recursion_limit` to **9,999** (`deepagents/graph.py:1039`; LangGraph's default is 25). Nothing in our code caps model calls, steps or wall time (`chat.py` `_run`, `agent.py`). Each loop step re-sends a growing history; past 100k tokens Haiku 5.5 bills 5x. The unfinished Q3 case died with "credit balance too low", which is what a drained balance looks like. | Most likely. Not proven. |
| Unfinished Q3 case (`follow-up-from-a-profile`) | Both Q3 result files hold 7 records. A record is appended only after `ask()` returns, so the case raised in both runs, and a killed or hung run writes no file at all (the file is written at fixture teardown). Code alone cannot tell hang from loop. The candidate loop is structured output: `ToolStrategy(ModelAnswer)` has `handle_errors=True` (`langchain/agents/structured_output.py:244`), so every validation failure (for example a `section` or `kind` outside the Literals) sends an error message back to the model with no cap except 9,999. The Q2 twin of this case passes. | Decide in Stage 3 with a call limit. |
| Model settings | `AGENT_MODEL` and `JUDGE_MODEL` default to `claude-haiku-5-5`, both read from env (`config.py`). Saved runs record haiku-5-5 for both. `ChatAnthropic(thinking=None)`; I could not confirm whether Haiku 5.5 thinks by default (docs list adaptive-on only for Opus 5 and Sonnet 5). Judge is the same model as the agent. Judge prompt includes up to 80,000 chars of records per rubric item (`test_agent_eval_q01.py:129`). | Instrumentation shows output tokens. |
| Retries below `ask()` | (1) `ToolStrategy` re-prompts on validation errors, unbounded. (2) Anthropic SDK `max_retries=2` (failed requests are normally not billed). (3) `ModelRefusalMiddleware`. (4) Summarization middleware retries on context overflow. (5) `ask()` retries once on a flagged number. | (1) is the real exposure. |
| Prompt caching | On: `AnthropicPromptCachingMiddleware` is appended unconditionally (`deepagents/middleware/_prompt_caching.py`), 5 minute TTL, tags the system message, the last tool and the message tail. Minimum cacheable prompt for Haiku 5.5 is **512 tokens**; our fixed prefix is about 5-6.5k, so it qualifies. Cases run back to back, so reads should hit. Unmeasured: nothing logs cache read or write tokens. | Likely working; verify in Stage 2. |
| Deep Agents overhead | `agent.py` already excludes the 10 built-in tools and the general-purpose subagent via a harness profile, so `task` is not exposed. Middleware still in the stack: Filesystem (tools filtered; no prose by default), PatchToolCalls, Summarization (idle until near the context limit), prompt caching, UnsupportedContent, ModelRefusal. The prior doc's "Deep Agents base prompt, about 2.3k chars" is unverified for 0.7.41: `graph.py` authors no base prompt unless the Anthropic harness profile defines one. | Measure the real request in Stage 1. |
| Plain LangChain enough? | Yes functionally: 3 tools, structured output, in-memory checkpointer. The product uses no files, subagents, planning, skills or memory. But the token saving is probably small; the real gain is control of the loop. Cheaper first step: pass `recursion_limit` in the run config and keep Deep Agents. Decide after the measured payload diff. | Recommend measure, then decide. |
| Days of use | 2026-11-23: 10 Q1 runs (judge on, 15 rubric calls each), 2 Q2 files, 2 Q3 files, plus any notebook re-executions (`make notebook` runs ten scenarios; `notebook-check` runs them again) and `make chat`/`make ui`. All agent paths share one `ANTHROPIC_API_KEY`. Even generously (about 600 agent calls, 250 judge calls) this is about $1-2 at Haiku 5.5 prices. | Cannot explain $35. |

**Console data from you:** 2026-11-23 was **640M tokens, all Haiku 5.5**. A full run is about 0.5M, so that is over 1,000 runs' worth of tokens (about 90k calls at 7k each, or fewer, far larger calls). This rules out (b) and (c) and fits a runaway loop: priority is the call limit, timeout, `recursion_limit` and `EVAL_MAX_USD`, all in and tested with the fake model before any live call.

## Stage 1: instrumentation and guards (scripted fake model only)

- **Keys.** `EVAL_ANTHROPIC_API_KEY` (eval runner: agent under test and judge) and `AGENT_ANTHROPIC_API_KEY` (chat, UI, notebooks). Model builder in `watchline/agent/config.py` takes the key explicitly (`ChatAnthropic(api_key=...)`), so a stray `ANTHROPIC_API_KEY` is never used. The eval fixtures fail (not skip) with a clear message if the eval key is unset. Update `docs/env.example` (new file; none is tracked) and `docs/process.md`, `CLAUDE.md` conventions line, `Makefile` help text. You put real values in `.env`.
- **Recorder.** One LangChain callback (`watchline/evals/usage.py`) attached via config to every model call, agent and judge: input, output, cache-read, cache-write tokens from `usage_metadata`, per call. Aggregated per case and per run, written to `build/agent-eval/usage-<timestamp>.json`, summarised at the end of the run with estimated dollars.
- **Prices** in `watchline/evals/pricing.py` with the source URL and fetch date in the file: Haiku 5.5 $0.10 in, $0.125 cache write, $0.01 cache read, $0.50 out (prompts over 100k: $0.50, $0.625, $0.05, $2.50); Sonnet 5.5 and others added only if used. Unknown model means the run refuses to start.
- **Safety.** `EVAL_MAX_USD` (default 0.25, printed at start) checked after every call; exceeding it raises and aborts the run. `EVAL_MAX_CALLS` per case (default 12) counted at call start. Per-case wall-clock timeout (default 90 s) plus the HTTP client timeout. `recursion_limit` set in the run config. Results file written per case as it finishes, so a killed run still leaves a record.
- **Judge records cap.** The records text sent per rubric item (now cut at 80,000 chars in `judge()`) gets a configurable limit, `EVAL_JUDGE_MAX_CHARS`, default 12,000 (about 3k tokens; the largest measured tool result is 15.4k chars, so a typical case is whole and an outlier is cut). When it truncates, log case, item, original and kept size, and note it in the run summary and the judge's prompt ("records truncated"). Tested with the fake model.
- **Payload snapshot.** With the fake model, dump the exact request (system text, tool schemas, `ModelAnswer` tool) and its token estimate. This settles the Deep Agents overhead and the plain-LangChain question.
- **Tests (fake model, in `make test`).** Cost math and cache split; cap aborts at the right call; call limit and timeout abort; missing key refuses; fake-model loop (validation error forever) stops at the limit.

### Stage 1 result (done, fake model only, no live calls)

- **Payload measured** (`tests/test_agent_payload.py`): Deep Agents adds **0 chars** of system prose and no tools beyond ours (`ModelAnswer`, `building_profile`, `registered_owner`, `deed_vs_owner`). System prompt 10,614 chars (all ours) plus 7,350 chars of tool schemas, about 4.5k tokens by the 4-chars rule (more with Haiku 5.5's tokenizer). The earlier "Deep Agents base prompt, about 2.3k chars" figure was wrong. Swapping to plain LangChain would save no tokens; the harness is not the cost. Decision: keep Deep Agents, cap the loop through config.
- **Done:** `watchline/evals/pricing.py` (Haiku 5.5 table, source and date in the file), `watchline/evals/guard.py` (usage recorder plus limits), `watchline/agent/config.py` (separate keys; `ANTHROPIC_API_KEY` is no longer read), `RECURSION_LIMIT = 30` in `chat.py` for every `ask` (the eval config sets `2 * EVAL_MAX_CALLS + 2`), eval harness wired in all three agent eval files (`run_case`, one session guard, per-case usage in the results JSON, usage file written after every case), judge records cap, `Makefile`, `CLAUDE.md`, `docs/process.md` and the agent notebook text updated.
- **Limits and defaults:** `EVAL_MAX_USD` 0.25 for the whole run (printed in the pytest header, summary at the end); `EVAL_MAX_CALLS` 12 per case; `EVAL_CASE_TIMEOUT_S` 90 (checked before each model call, plus a 60 s HTTP timeout on every request); `EVAL_JUDGE_MAX_CHARS` 12,000, with the cut logged, recorded in the usage file and marked in the judge's prompt. A missing `EVAL_ANTHROPIC_API_KEY` fails the run (not skips).
- **Tests** (`tests/test_eval_guard.py`, 17, plus the payload test): cost math including cache split and the over-100k tier; unknown model refused; per-call, per-case and per-run recording with the usage file; spend cap aborts the run and later cases cannot start; a looping model (invalid `ModelAnswer` forever) stops at the call limit and the next case runs; timeout; an abort swallowed by the `ask` correction retry still fails the case through `check()`; step limit stops a loop with no guard; judge truncation and its log; key separation. `make check`: 235 passed.
- **Not covered, named:** a call that hangs inside the HTTP client is bounded only by the 60 s request timeout (times the SDK's 2 retries); the timeout is not a hard kill. Judge calls made after a case ends count toward the run cap but not that case's usage. Cost is an estimate from logged tokens until Stage 2 reconciles it with the Console.
- **`.env.example`:** the permission rules deny writes to that path, so the template is at `docs/env.example`; copy it with `cp docs/env.example .env.example`. I did not touch `.env`.
- **You must add** `AGENT_ANTHROPIC_API_KEY` and `EVAL_ANTHROPIC_API_KEY` to `.env` before any live run (chat, UI and notebooks stop working until `AGENT_ANTHROPIC_API_KEY` is set).

*Stop for your review.*

## Stage 2: one live case

Case `no-borough` (clarification, one tool call, about 2 model calls). Maximum cost: **$0.25 cap**; expected under $0.01. Then reconcile the logged cost against the Console for the eval key. If they differ by more than 20%, stop and fix the price table (and the cache-token accounting) before Stage 3. No live call happens before every Stage 1 guard is in and tested with the fake model.

### Stage 2 result (live, 2026-11-24)

Ran `test_agent_eval_q01[no-borough]` once, cap $0.25, call limit 6, timeout 60 s. It passed in 3.6 s. Logged: **2 calls, 11,474 input tokens (5,667 cache read, 0 cache write), 201 output tokens, estimated $0.0007.** Per call that is about 5.7k input tokens, above my 4.5k chars/4 estimate (Haiku 5.5's tokenizer). Caching works: the second call read 5,667 tokens from cache. Cache writes show 0 on both calls, which is odd (the first call should have written the prefix unless it was already cached by a recent run on this key); if the API reports writes somewhere we do not read, the estimate is slightly low (writes cost 1.25x base). Reconciliation with the Console is **pending your reading of it**: the eval key's usage for this run should be about 11.5k input, 5.7k cache read and 0.2k output tokens, about $0.0007. A single request this small may not show at the Console's resolution; if so, Stage 4 (about 25 calls) is the better check, and the 20% rule applies to that.

## Stage 3: the unfinished Q3 case alone

`follow-up-from-a-profile`, call limit 8, timeout 90 s, cap $0.25 (expected under $0.02 if it behaves). Report: hang, loop, or error, with the message sequence.

### Stage 3 result (live, 2026-11-24): a loop, caught by the guard

`follow-up-from-a-profile`, call limit 8, timeout 90 s, cap $0.25. Run twice (the second added a per-call message trace to the usage file; same limits). Both stopped at the 8-call limit in under 8 s: **$0.0035 and $0.0015** (first: 119k input tokens, 97k of them cache reads, 584 output). So the case is neither a hang nor an answer failure: **it is a tool-call loop in turn 1** (`Give me a profile of 5413 7 Avenue, Brooklyn.`). The trace shows every call after the first is sent the `building_profile` result as its newest message, and the history grows by 2 messages per call (the model's tool call, then the result): the model calls `building_profile` again and again with the same lot and never returns `ModelAnswer`. It is not the structured-output validation loop I suspected. Turn 2 (the deed question) was never reached. Before our limits this would run to the 9,999 step limit, with history growing each step, which fits the 640M tokens on 2026-11-23.

**Probe (no model, `scripts/probe_profile.py`, run by you):** the result for this address is small: 4,940 chars (about 1.2k tokens), one building, 16 list entries, normal caveats, nothing in the tail that asks for more. So causes (a) and (b) are out: the loop is not caused by a big or incomplete-looking result. The 15k input per call came from the loop re-adding that result to the history on each repeat. What remains: the model's own choice to call again. The trace did not show what it said before each repeat, so I added that (its tool call name and arguments and any text, per call; tested with the fake model) and have not yet run it live. The Q1 profile cases (`224 54 Street`) do not loop, so the wording "Give me a profile of ..." or this lot may matter. I have not changed the prompt or tool.

Next options, none run: (1) a no-model call of `building_profile` for this address to read the result's size and tail (needs Neo4j and the sidecar; it reads `.env` through the app's own code, so I need your go-ahead); (2) replay the saved history with the fake model to test a loop guard in `ask` (stop on a repeated identical tool call); (3) one more live run only after a change, same limits. The guard already makes the failure cheap; the fix for the loop itself is a product change, so it is yours to approve.

**Third run, with the model's own calls in the trace ($0.0036, 8 calls, stopped by the call limit):** every one of the 8 calls is the model emitting the same single tool call, `building_profile(address="5413 7 Avenue", borough="Brooklyn")`, with no text, right after receiving the identical, correct result. No error, no `ModelAnswer` attempt, no validation message: the model never moves on to the structured answer. Stage 3 total across three runs: about $0.0086. Cause in one line: **Haiku 5.5 repeats the identical lookup instead of answering** for this question; the data, the tool result and our code are not what loops. Why this question and not the Q1 profile cases is not established (the arguments are the same shape as the passing Q2 cases, which also pass the borough separately).

Proposed fix, for your approval, not made: a repeat guard in the tool layer. If `building_profile` (or any tool) is called a second time on one thread with the same arguments, it returns a short fixed message ("You already have this result; answer now with the structured answer") instead of the data or a new lookup, and the repeat is counted and shown in the usage log. It is a product change (it also protects the chat and the UI from the same loop), tested with the scripted fake model, then one live rerun of this case at the same limits (about $0.004). If the model still does not answer after the nudge, the next lever is the prompt, with an eval for it.

### Stage 3 fixed: repeat guard (live rerun passed)

`watchline/agent/repeat_guard.py`: `RepeatGuardMiddleware`, wired into `build_agent`. Within one turn (everything after the latest human message), a tool call identical in name and arguments to an earlier answered call is not run; it returns `{"status": "repeat_lookup", ...}` telling the model it already has the result and should write its answer. The first call always runs; different arguments run; a new turn may look up again. Blocked repeats are kept on the middleware (`.blocked`) and show in the call trace as a `repeat_lookup` tool message. Fake-model tests (4 added): nudge not run, per-turn and per-arguments scope, a model that ignores the nudge is still stopped by the call limit. `make check`: 238 passed.

Live rerun of `follow-up-from-a-profile` (limits 8 calls, 90 s, $0.25): **passed**, 5 calls, 9.9 s, **$0.0018** (47.6k input of which 44k cache read, 1.9k output). The trace: the model repeated the lookup once, got the nudge, answered; turn 2 called `deed_vs_owner` and answered. Stage 3 total across four runs: about $0.0104. Caveats: one passing run shows the guard unblocks this case, not that the model stops repeating (it still repeated once, one wasted call); the cause of the repeat is still unknown, and the Q1/Q2 profile paths now run through the guard too (their tests pass). Cache writes still read 0 in every run.

### Cache-write accounting fix (no live call)

The recorder showed 0 cache writes in every live run. Cause, in `langchain_anthropic/chat_models.py` `_create_usage_metadata`: when the API returns the per-TTL breakdown, langchain sets `cache_creation` to 0 and reports writes under `ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`; we read only `cache_creation`. The writes were still inside the input total, so they were billed in our estimate as plain input (1x) instead of 1.25x (5 min, what the caching middleware uses) or 2x (1 hour). Fixed in `watchline/evals/guard.py` (reads all three keys; logs `cache_write_tokens` and `cache_write_1h_tokens`) and `watchline/evals/pricing.py` (1h write price: Haiku 5.5 $0.20, over 100k $1.00; the table is now 1.25x / 2x / 0.1x of input, checked by a test). Four fake-model tests, built from real Anthropic `Usage` objects through langchain's own converter: per-TTL writes logged and priced at 1.25x, the generic-only field, 1h at 2x, the price ratios. `make check`: 242 passed. Effect on earlier numbers: the estimate was low by 25% of the write tokens' base price, at most about 20% of a cold-cache single case (for `no-borough`, up to about $0.00014 of $0.0007); warm-cache runs barely change. The Stage 2 and 3 usage files keep their old figures. Stage 4 will show real writes.

## Stage 4: about five cases once

Q1 `d-multi-building`, `battery-place-two-counts`, Q2 `a-registered-owner`, Q3 `a-exact-match-is-not-same-party`, `zero-amount-is-not-a-sale`. Cap $0.25 each case, run cap $1.00 (stated before running). Report cost per case with cache-hit rates.

## Stage 5: no full run without your go-ahead.

## Per-case audit (29 cases)

Every case already checks: structured answer exists, kind, caveat codes, evidence resolves, numbers guard, must-match and forbidden phrasing. Gaps I would close for all cases: **tool-trace assertions** (tool called with the address argument, called once per address, no tool called twice with the same args, call count within the limit), **lead labelling** on ownership answers (text says "recorded" or "lead" near any name comparison), and a **summed-severity check** (no number in the text equals the sum of two or more sibling counts, even if that sum happens to exist elsewhere in the tool result). Per-case additions:

| Case | Current criteria | Proposed deterministic assertions | Left for a judge (yes/no) |
|---|---|---|---|
| Q1 d-multi-building | kind, 2 caveats, 4 ids, no "3 buildings" regex; 2 rubric | All 3 BINs appear in facts' evidence; addressed BIN 3324451 in a fact with `bin` evidence; "18" appears only in a fact with `characteristics` evidence and no BIN | None; both rubric items become evidence checks |
| Q1 battery-place-two-counts | kind, code, BBL; 2 rubric | Both 2 and 1 present, each fact's evidence section is `counts`; no fact states one count alone | None |
| Q1 unregistered-lot | kind, code, BBL, 2 forbidden regexes; 2 rubric | Zero facts with `buildings` BIN evidence; phrase "HPD" present; existing regexes | None |
| Q1 variant-spelling | kind, code, BBL | `resolution` evidence fact exists; typed and matched strings both in text | None |
| Q1 ambiguous-street | clarification, code, "SMITH STREET", no 10-digit id; 1 rubric | Question mark in summary; no BBL anywhere in facts' evidence | None |
| Q1 no-borough | clarification, borough/ZIP; 1 rubric | Question mark; tool status `needs_borough`; no BBL | None |
| Q1 not-found | kind, code, no id; 1 rubric | Tool status `ok` with outcome `not_found`; no BBL in facts | None |
| Q1 harassment-finding | kind, code, BBL; 2 rubric | Phrase "After Inquest" or "After Trial" present with count 1 from `harassment_findings_after_inquest_or_trial`; "harassment" never next to "found/finding" outside that phrase | "Does the answer call any case type 'Harrassment' a finding?" (residual) |
| Q1 slumlord-trap | kind in {refusal, profile}, code, no "slumlord"; 2 rubric | Text contains a decline phrase ("cannot"/"can't"/"do not judge"); no ranking words (worse, worst, better); summed-severity check | None likely |
| Q1 sum-trap | kind, 2 codes; 1 rubric | Summed-severity check (the key assertion); every category number present as listed; no "total"/"in all" | None |
| Q1 follow-up-same-thread | kind, BIN; 1 rubric | Turn 2 makes no new `building_profile` call, or one with the same lot; BIN 3324448 and BBL 3008210012 in the same fact | None |
| Q2 a-registered-owner | kind, 3 codes, 3 matches, 2 forbidden; 2 rubric | Dates 2025-09-30 and 2026-09-01 present; owner type "corporate" present; "registered owner" wording; no "holds title" | None |
| Q2 who-owns-is-not-title | kind, code, 2 matches, 2 forbidden; 1 rubric | Text says "registered owner" or "registered"; forbidden title phrasing | None |
| Q2 ended-registration-not-current | kind, 2 codes, 3 matches, 2 forbidden; 2 rubric | Compare end date to snapshot date in code: text contains "ended" or the end date and not "current"; any person name appears with an "individual" role word in the same fact | "Is the person's name used only as the individual owner?" (residual) |
| Q2 owner-name-spellings-kept | kind, 2 codes, 8 matches; 2 rubric | Exact strings `HDFC INC.` and `HDFC INC` each in a separate fact with its own BIN evidence; not merged (no fact holds both) | None |
| Q2 two-registrations-one-without-owner | kind, 2 codes, 2 ids; 2 rubric | Both ids in separate facts; fact for 11009 cites no owner name; "not recorded"-style phrase | None |
| Q2 no-hpd-building-no-owner-inferred | kind, code, BBL, 4 forbidden; 2 rubric | Zero registration facts; existing regexes | None |
| Q2 registration-current-at-snapshot | kind, code, 2 matches; 2 rubric | Both dates in one fact; text contains "snapshot" or "2026-05-29"; no "currently"/"today" outside a hedge | None |
| Q2 no-borough | clarification, borough/ZIP, forbidden id/HDFC; 1 rubric | Same as Q1 no-borough | None |
| Q2 follow-up-from-a-profile | last tool, kind, code, id; 1 rubric | Last-turn `registered_owner` args resolve to the same lot as turn 1 (same address string or bbl) | None |
| Q2 managing-agent-trap | kind in {refusal, registration}, 2 forbidden; 1 rubric | No `registered_owner` or other tool result name appears as "managing agent"; text contains a "cannot/not" decline | None |
| Q3 a-exact-match-is-not-same-party | kind, 4 codes, 3 matches, 3 forbidden; 2 rubric | Name-agreement fact and address-agreement fact are separate facts, each with `comparison` evidence; outcome strings `exact_normalized` and `same` present as given; lead labelling | None |
| Q3 g-spelling-difference-not-resolved | kind, 2 codes, 4 matches, 2 forbidden; 2 rubric | Both grantees in separate facts; no sentence containing both "K S TURNPIKE" and "KS Turnpike" with "same"/"identical" outside a hedge | None |
| Q3 zero-amount-is-not-a-sale | kind, code, 5 forbidden; 1 rubric | Amount "0" present in a `deeds` evidence fact; "recorded 2025-04-02"; deed-not-sale code present | None |
| Q3 tied-deeds-all-listed | kind, 2 codes, 4 matches; 1 rubric | Both document ids in separate facts; date 2011-06-15 present; count of deed facts equals deeds in the tool result | None |
| Q3 who-owns-not-from-the-deed | kind, 1 match, 3 forbidden; 1 rubric | `deeds` and `owners` evidence in separate facts; forbidden ownership phrasing | None |
| Q3 no-deed-is-not-never-sold | kind, code, match, 3 forbidden; 1 rubric | Zero facts with `deeds` evidence naming a grantee; 15 STONE LLC only in a fact with `owners` evidence | None |
| Q3 multi-lot-deed-not-lot-specific | kind, 2 codes, 2 ids; 1 rubric | Both ids; "16" and "45839605" appear in the same fact as `otherLots`/`amount` evidence; "price" never attached to the amount | None |
| Q3 follow-up-from-a-profile (unfinished) | last tool, kind, match; 1 rubric | Last turn calls `deed_vs_owner` for the profiled lot; no violation/complaint/litigation words in the final text | None |

Result: all 29 rubric sets can move to deterministic checks except two residual yes/no questions (Q1 harassment-finding, Q2 ended-registration). Everything else is a judge-free run, so the judge becomes optional and narrow. Risk: regex checks are brittle to paraphrase; the evidence-based checks (which fact cites which section) are not, so prefer those.

## Proposed setup: tiers

| Tier | When | What | Runs | Est. cost (Haiku 5.5, unmeasured until Stage 4) |
|---|---|---|---|---|
| 0 | every change | `make test` and `make eval` (tool-level, no model) plus agent logic against the scripted fake model, and replay of recorded model turns | none | $0 |
| 1 | before merge | Live smoke: about 6 cases (one per tool, one clarification, one trap per question; the follow-up case once Stage 3 is understood), deterministic checks only | 1 | $0.05 to $0.15; hard cap $0.50 |
| 2 | prompt, model, tool description or `ModelAnswer` change | All 29 cases, deterministic checks | 1 (second run only on failure) | $0.10 to $0.40 expected; cap $2 |
| 3 | same triggers, plus judge changes | Tier 2 plus the 2 residual judge questions and the judge calibration | 1 | under $1; cap $5 |

Supporting measures: one run by default (`EVAL_RUNS=1`; repeats are opt-in); **cache model outputs** keyed on (prompt hash, tool-schema hash, model, case, turns) in `build/agent-eval/cache/`, and judge verdicts keyed on (rubric, answer, records), so re-checking after a checker change costs nothing; record and replay of full model turns so the numbers guard, assembly and checks are tested without the model; a loop guard and spend cap on every live run; notebooks are not re-executed on merge (run `make notebook` only when its scenarios change).

**Coverage risks, named:**
- The smoke set can miss a regression in a case it skips (mitigation: Tier 2 on any prompt or tool-description change, which is when behaviour changes).
- Cached outputs hide model drift (mitigation: key includes the model id and prompt hash; Tier 3 runs with the cache off).
- One run hides flakiness (earlier history shows 8 to 11 of 11 across repeats); re-run failures once, and run three repeats only at Tier 3.
- Replay tests our code after the model, not the model.
- Deterministic regexes can pass a bad paraphrase; the two residual judge questions and a periodic Tier 3 cover that.
- Dollar figures are estimates until Stage 2 reconciles them with the Console.

## Verification

Stage 1: `make check` (fast tests incl. new fake-model tests). Stage 2: logged cost against Console for the eval key. Stages 3 to 4: logged per-case cost and cache-hit rate.
