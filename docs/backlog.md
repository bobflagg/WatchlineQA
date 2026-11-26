# Backlog

One feature per session: start with `/feature <id>`, finish with `/wrap`, then `/clear`. Entries are small enough
for one session. A blocked or `needs-you` entry is not started.

States: `ready` (can start now), `needs-you` (the developer must decide or supply something first),
`blocked` (waiting on new data or another entry), `hold` (the developer said wait), `later`, `done`.

Entry shape: id, title, state, one paragraph, **Needs** (if any), **Model calls** (none, or the maximum cost),
**Plan** (link, once one exists).

Reconcile against `git log` when you work on F00; some entries may already be done.

## Ready
_No entries are ready right now._

## Needs you
- **F02 Snapshot dates from the graph.** needs-you. Dates such as "HPD registrations through 2026-05-29" are text in
  the code. They should come from a metadata node. **Needs:** how the rebuild will write that node.
  **Model calls:** none.
- **F04 Complaints (Q27).** needs-you. **Needs:** the question spec and the data. **Model calls:** none.
- **F05 Pest violations (Q15.3).** needs-you. **Needs:** the list of order codes.
- **F06 Berkovics contrast case.** needs-you. **Needs:** a decision on whether it is a demo address (11 leads).
- **F07 A landlord from JustFix or HDC.** needs-you. **Needs:** the developer asks them for a landlord whose
  records they know well; then probe it like the demo landlords in `docs/plans/report-graph.md`.
- **F14 Console cost reconciliation.** needs-you. **Needs:** the Console figure for the eval key on 2026-11-24
  (expect $0.14 to $0.21 within the 20% rule; if it stays near $0.05, the price table or key attribution is wrong).
- **F16 The `specs/` symlink.** needs-you. **Needs:** keep it untracked, track it, or copy the files.

## Blocked
- **F08 Re-check the demo numbers on the rebuilt graph.** blocked on the new snapshot. Live tests, eval cases, the
  two backup runs and `docs/plans/report-demo-verification.md`. **Model calls:** none.
- **F09 Completeness check against Open Data.** blocked on the new data.

## Later
- **F10 Narrative layer behind the firewall.** later (early January). See "Two layers" in
  `docs/plans/report-graph.md`. **Needs:** a stated maximum cost and approval before any live run.
- **F12 Explainers.** later. Address resolution and the profile pipeline first, then the agent flow, then the report
  flow (hold: the developer said to wait on the report explainer). Use `pipeline-explainer`.
- **F13 Diagnose the repeated lookups.** later. Why the model repeats an identical tool call on the profile-first turn
  of the follow-up cases (see `docs/history.md`). **Model calls:** small; cap stated first.
- **F15 Hooks and `make doctor`.** later. Commit-time checks; a Neo4j and sidecar check; `make explainer`.
- **F17 Web research step.** later, after the graph side is solid. Web results are context, never identity evidence.
- **F18 Streamlit follow-ups.** later. Brand banner, per-kind renderers and lead/finding pills, streaming.

## Done
Done features are recorded in `docs/status.md`, one line each.
- **F00 Reconcile status and backlog.** done (2026-11-26). Move the current `docs/status.md` to `docs/history.md` (archive, not
  read in feature sessions), write a new `docs/status.md` of about 40 lines (done features one line each, next, decisions,
  open questions), and fix anything stale (for example Q5 entity research is built). Reconcile this backlog with
  `git log`. **Model calls:** none. Do this first.
- **F11 Report page review and navigation.** done per `git log` (`9737016`, `838747f`, `53c4c40`, `2f07441`); developer to confirm. Look at the report page in a browser on
  both demo addresses; add sample questions for the new tools; merge the report page into the chat app's navigation.
  **Model calls:** none.
- **F01 Graph schema check.** done (2026-11-26). `make schema-check`; plan: `docs/plans/schema-check.md`. **Model calls:** none.
