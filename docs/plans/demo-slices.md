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
- **C steps 1 to 3 (done).** `watchline/identity/checkpoint.py` (pure links, decisions, portfolio effect) and `watchline/identity/graph.py`
  (graph reads and `build_inputs`). `watchline/identity/section.py` adds the section, its JSON view, the decision log file and the templated Answer (kind
  `identity_checkpoint`, no model, UI fixtures and tests). Step 4 (LangGraph checkpoint) remains.
- **D. Conditions, Q15 and Q28 (after C).** Counts by class and status, never summed. Harassment finding only for After Inquest or After Trial.
  Q27 complaints later.

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
- Agent-level evals for `deed_timeline` and `building_contacts`; `/code-review` of Slices A and B; explainer updates; sidebar sample questions
  for Q4 and Q12; a look at the new fixtures in a browser.
