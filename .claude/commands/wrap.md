---
description: Close out the current feature session (status, backlog, staging, commit message)
---

Close out this session. Do not start new work.

1. Run `make check`. If it fails, fix it or say plainly what is failing.
2. Update `docs/status.md`: one line for this feature (what it does, where it lives, the plan file). Details belong
   in the feature's `docs/plans/<name>.md`, not in status. Remove anything in status that is now done or false.
   Keep status.md short (about 40 lines).
3. Update the feature's entry in `docs/backlog.md` (state `done`, plus the commit or plan pointer). Add entries for
   any leftovers or new ideas; do not start them.
4. Record decisions or open questions in the plan file, not in status, unless they affect later features.
5. Stage the files for this feature by name. Never stage `specs/`, `.env` or build output. Show the staged list.
6. Propose a commit message. Do not commit unless the developer asked.
7. Print: what was done in two sentences, anything not done or not verified, the next three `ready` entries from
   the backlog, and "Safe to /clear".
