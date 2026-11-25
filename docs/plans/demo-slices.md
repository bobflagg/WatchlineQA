# Demo slices (plan approved 2026-11-25, revised the same day)

Goal: the next slices toward the mid-January 2027 demo (see `docs/plans/report-graph.md`). Section functions are deterministic, with no
LLM. Order was changed after review: the identity checkpoint is Slice C and conditions are Slice D.

## PESP steps 3 to 8 against the questions
| Step | Questions | State (2026-11-25) |
|---|---|---|
| 3 Registered owner, contacts | Q2, Q4 | Q2 done; Q4 done (Slice A, `75410a8`) |
| 4 Deed history | Q3, Q12, Q13 mortgages, Q18 restructuring | Q3 done; Q12.1 timeline done (Slice B, `022c343`); Q12.2 portfolio deeds, Q12.3 attribution, Q13, Q18 not built |
| 5 Entity research | Q5 DOS record | not built |
| 6 Related entities | Q6 mail-drop, Q7 shared evidence, Q22 same entity or not, Q11 | not built; Q22 and Q7 are Slice C |
| 7 Portfolio | Q8 network, Q9 portfolio, Q10 layers differ, Q23 agent footprint | not built; Q9 effect is part of Slice C |
| 8 Conditions | Q15 violations, Q27 complaints, Q28 litigation, Q21 | not built; Q15 and Q28 are Slice D |
Every step 3 to 8 has a question. No question: step 9 (web research; only Q24 and Q25 touch it) and step 10 (Q20, the dossier, is closest).

## Slices
- **B. Q12.1 deed timeline (done).** `watchline/deeds/timeline.py`, tool `deed_timeline`, kind `timeline`, sections `timeline` and
  `timeline_counts`. Counts of deeds, not-a-sale and amount-0 are separate and cover the whole period. Evals: `tests/evals/q12_cases.yaml`.
- **C-design. Identity checkpoint design note (done).** `docs/plans/identity-checkpoint.md`. Open questions are listed there.
- **A. Q4 contacts (done).** `watchline/contacts/contacts.py`, tool `building_contacts`, kind `contacts`, section `contacts`. Evals:
  `tests/evals/q04_cases.yaml`.
- **C. Identity checkpoint, Q22 and Q7 with the Q9 effect (next, after the design note's open questions are answered).** Accept or reject the
  BADHUMI link and the portfolio count changes (55 lots and 176 units as held; 56 and 179 if accepted). Decisions are an input and the
  graph never changes. Build order is in the design note.
- **C steps 1 to 4 (done).** `watchline/identity/checkpoint.py` (pure links, decisions, portfolio effect) and `watchline/identity/graph.py`
  (graph reads and `build_inputs`). `watchline/identity/section.py` adds the section, its JSON view, the decision log file and the templated Answer (kind
  `identity_checkpoint`, no model, UI fixtures and tests). Shared-registration evidence added (BAHUMI and BADHUMI are both listed on HPD registration 205148, so the BADHUMI link has two leads, address and
  registration). Step 4: `watchline/report/graph.py`, a LangGraph workflow (propose, pause with `interrupt()`, finish) that
  takes the researcher's decisions on resume and saves them as the JSON log; no model. Next for the report graph: the other PESP sections as
  nodes, report export, and the narrative layer.
- **D. Conditions, Q15 and Q28 (done).** `watchline/conditions/conditions.py`; tools `open_violations` (kind `violations`, sections `violations` and
  `violations_rate`) and `litigation_cases` (kind `litigation`, sections `cases` and `case_counts`). Counts by class, status and type, never summed;
  harassment finding only for After Inquest or After Trial; a respondent matching an owner name is a lead. Evals `tests/evals/q15_cases.yaml`,
  `q28_cases.yaml`. Not built: Q15.3 pest violations (needs the pest order-code list), Q27 complaints.
  Demo note: the one harassment finding on the BAHUMI lot 74 Clinton Place (After Trial, 2016, penalty 5200) names an individual respondent, not a
  BAHUMI party and not the registered owner (74 CLINTON PLACE LLC). It is a finding on the building. Do not present it as a finding about the landlord.

## Live probe (read-only, 2026-11-25)
- `Violation.status`: `Close`, `Open`. `violationClass`: `A`, `B`, `C`, `I` (all eight combinations exist).
- `Litigation.harassmentFinding`: null (203,962), `No Harassment` (5,990), `After Inquest` (167), `After Trial` (50). Only the last two are a
  harassment finding.
- Open violations by class (A, B, C, I): Bahumi 181, 345, 322, 9; Berkovics 14, 38, 47, 3. A harassment finding (After Trial) exists on
  Bahumi lot 2032070010, BIN 2014484.

## Demo fixtures (looked up by landlord name, never by run-local portfolio id)
- `YONATAN BAHUMI`: the main record covers 55 lots (all HPD-registered, 176 units); 354 deeds, 239 with amount 0.
- `YONATAN BADHUMI` (misspelled): covers lot 2030370098 (2141 Washington Avenue, Bronx), 3 units, 9 deeds, 7 with amount 0, recorded 1966 to
  2002 and naming no Bahumi party. The lot is not among the 55. It is linked to BAHUMI only by `CONNECTED_BY_ADDRESS` (3 edges, weight 5.44).
  The 1978 deed also names 1,075 other lots.
- `MOSES BERKOVICS`: six landlord records joined by identity edges; the contrast case. Its lots and deeds are not yet probed.

## Tests
- No model calls: unit tests with fake graphs, `answer.py` evidence tests, UI fixture tests (`tests/test_ui.py`), and live tool-level evals
  (`make eval`, now including Q4 and Q12).
- Agent-level evals for the new tools are not written. If wanted: Haiku 5.5, judge off, about $0.025 per 29 cases, so under $0.01 for about
  eight new cases. Cap `EVAL_MAX_USD=0.10`, 8 calls per case. State the cost and get approval before any live run.

## Not done yet
- Agent-level evals for the four new tools (`tests/evals/agent_slices_cases.yaml`, `tests/test_agent_eval_slices.py`, 9 cases). First live run 2026-11-25
  (Haiku 5.5 agent and judge, judge on, cap $0.10, 8 calls per case): 5 passed, 4 failed, estimated cost $0.0123 (29 calls). Failures were three prompt gaps
  (the model cited another tool's section: `deeds`, `characteristics`, `owners`), one subtracted count, and one checker false positive ("not a finding that").
  Fixed and the 4 failed cases rerun (same cap, judge on, $0.0071, 15 calls): 3 passed; the fourth (`respondent-matching-the-owner-is-a-lead`) failed only on
  a checker false positive ("the records do not record which respondent is the owner" is a denial); the checker now treats "not record which/whether/that" as a
  hedge (tested offline against the recorded sentence). Rerun alone ($0.0018, 5 calls, judge on): passed. All 9 cases have now passed in a live run (across three runs, about $0.021 in total).
  Rerun of the five first-run passes after the prompt changes (2026-11-25, $0.0069, 15 calls, judge on): 3 passed, 2 failed. `how-bad-is-it-is-not-a-severity` failed on a checker false
  positive ("the records do not give a severity rating" is a denial; the pattern is now narrower, tested offline). `agent-is-not-the-owner` cited `registered_owners`, a section
  I added for litigation, in a contacts answer (prompt now says it is only for `litigation_cases`). Rerun of those two ($0.0036, 7 calls): `agent-is-not-the-owner` passed; `how-bad-is-it-is-not-a-severity` failed on a new cause (the model cited `characteristics`
  for the lot's year built, class and units in a violations answer). A `lot` section now lets a fact cite the lot's own values; rerun alone ($0.0018, 3 calls): passed, citing `violations_rate` and `lot`.
  Full run of all 9 on the final prompt (2026-11-25, $0.0128, 32 calls, judge on): 8 passed, 1 failed (`zero-amount-deeds-are-not-sales`: the judge wanted "amount 0 is not a sale"
  said outright, and the model again wrote "the other 2", a subtracted count). `respondent-matching-the-owner-is-a-lead` passed but used 6 calls (it also called three other tools, and the numbers guard
  caught "four" and "three"). Then: `withAmount` count and a `plain` sentence on the timeline counts, and a prompt line keeping respondent questions to
  `litigation_cases`; those two cases rerun ($0.0048, 8 calls, judge on): both passed (the respondent case now calls only `litigation_cases`, with one numbers-guard
  correction). Every case has now passed on the final prompt (before the review fixes below);
  `/code-review high` on these changes found 1 important and 5 smaller issues, all fixed offline (commit after `70186c9`): the timeline counts now partition the deeds
  (`amountZero`, `correctionDeeds`, `amountMissing`, `withAmount`, adding up to `deeds`); renderer-only sections (`links`, `decisions`, `portfolio_effect`) can no longer be
  named by the model or crash `assemble`; the shared hedge is scoped to the matched phrase with per-case `hedge_verbs`; the severity check forbids any rating wording
  unless the sentence denies giving one; the prompt's section mapping is a per-tool list. Full rerun of the 9 after those fixes ($0.0139, 35 calls, judge on): 8 passed; `finding-on-the-building-not-the-landlord` failed (the model opened with "Yes, … against the buildings" to a
  question about the owner). A deterministic check for an opening yes and a prompt line were added; rerun alone ($0.0020, 3 calls): still failed the opening-yes check (the judge passed it; the answer
  was precise after the "Yes"), so the model ignored the prompt line; a general summary rule (do not begin with yes or no when the records cannot establish it) was added and the case rerun
  ($0.0020): the model still opens with "Yes, one case on the building … records a harassment finding" (accurate about the building; the judge passed it), so the check still fails; The amount-0 case passes but the model still writes "the other 2"
  (a subtracted count); the judge accepted it; `/code-review` of Slices A and B; explainer updates; sidebar sample questions
  for Q4 and Q12; a look at the new fixtures in a browser.
