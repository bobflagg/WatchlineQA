---
description: Start one backlog feature in a fresh session (plan first, one feature only)
argument-hint: <backlog id, e.g. F01>
---

Work on exactly one feature: backlog entry **$ARGUMENTS** in `docs/backlog.md`.

1. Read only: `docs/status.md`, the entry `$ARGUMENTS` in `docs/backlog.md`, and the plan or doc that entry links.
   Do not read other plans, `docs/history.md`, notebooks or `specs/` unless the entry names them.
2. If the entry's state is `needs-you`, `blocked`, `hold` or `later`, stop. Say what is needed and wait.
3. Use plan mode. The plan is short: what changes, which files, the tests (deterministic first), whether any
   live model call is needed (if so, the maximum cost), and what "done" means. Wait for approval.
4. Build in small steps. Load the skills CLAUDE.md names for the work (Cypher, Streamlit, LangChain). Probe the
   live graph before writing expected values. Run `make check` before calling anything done.
5. Live model calls only under the cost rule in CLAUDE.md: cap set, maximum cost stated, approved.
6. For non-trivial work, ask a fresh-context subagent to review the diff against the entry and the ontology rules.
7. Do not start a second feature. Ideas and leftovers become new entries in `docs/backlog.md`.
8. When done, do the `/wrap` steps and stop.
