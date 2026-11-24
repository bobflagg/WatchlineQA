# Slice: Q3, deed grantee against HPD owner

Intent: Q3 (`specs/questions/q03.md`, Q3.1 to Q3.5). Type an address, get the most recent deed(s) on the lot with
every grantee, the HPD registered owners (Q2), and two separate agreement fields: name (exact normalized N1,
normalization match N2, different, not comparable) and address (A1: same, differs, absent).
Status: built on branch `q3-deed-vs-owner`, not committed or merged. Done: module, agent wiring, prompt, UI fixture and samples, fast tests, live tool-level evals. Not done: judge-graded agent evals, `make chat` and `make ui` by hand, and the fresh-context review.
Why this one: the first slice that returns leads, so it tests the lead-vs-finding rules.

## Checked live (2026-11-23)

- The graph has everything: `(Lot)-[:HAS_DEED]->(Deed)-[:HAS_GRANTEE|HAS_GRANTOR]->(Grantee|Grantor)`. No loader work.
- Deed props: `documentId`, `docType`, `recordedDate` and `docDate` (the MCP shows strings, but the driver returns `neo4j.time.Date`; `Neo4jDeedGraph.deeds` converts them to ISO strings), `docDate`, `amount`. Grantee and Contact
  props: `mailingAddress`, `addressLine2`, `zip` (not `zipCode`), `nameKey`; names are `name` (Grantee) and
  `corporationName` / `personName` (Contact). 202,728 of 203,804 owner contacts have `mailingAddress`.
- Doc types are stored with commas (`DEED, TS`, `DEED, LE`, `DEED, RC`), unlike the spec's `DEED TS`. Query the stored
  values: DEED, DEED, TS, DEED, LE, DEED, RC, DEEDO, DEEDP, CORRD, CONDEED. The graph has no `DEED COR`.
- Anchor A resolves to BBL 3008260002. Latest deed 2025032100031001 (recorded 2025-04-02, doc 2025-03-14, $0),
  grantee `5413 PLAZA LLC`. Prior deed 2021022201130003 ($5,000,000). Matches the spec.
- 6,178 of 195,377 deeded lots have tied latest deeds, so ties are real: return all, choose none.
- `specs/decisions.md` (named in the spec) is not in the symlinked folder. Rules come from the spec's Decisions section.
- Still to probe before writing expectations: anchor G (548 52 Street), a tied-deed lot, a no-deed lot, a worst-case lot.

## What already exists (reuse)

- `resolve_text` in `watchline/geosupport/resolution.py` and the resolution caveats.
- `registered_owners` in `watchline/registration/registration.py` (Q2), `Neo4jProfileGraph._read` pattern for
  read-only, timeout and `LIMIT`.
- Tool pattern in `watchline/agent/tools.py`, answer contract in `watchline/agent/answer.py`, `Caveat` constants.

## Design

New `watchline/deeds/deeds.py` with `deed_vs_owner(client, graph, dg, rg, text, **kw)`.

1. Resolve with `resolve_text`. Unresolved or not in the graph returns the resolution caveat only, as in Q2.
2. Deeds: one read for the deeds on the lot with the maximum `recordedDate` (all ties), each with its grantees (name,
   address, line 2, zip) and `otherLots` (count of other lots the deed names). `LIMIT`ed; truncation sets the existing caveat.
3. Owners: reuse `registered_owners` and extend its owner read to return `mailingAddress`, `addressLine2`, `zip`. Small
   change to Q2; its tests are updated.
4. Comparison is pure code at answer time, with no graph writes. `names.py`: `n1` (uppercase, trim, collapse whitespace),
   `n2` (n1, drop periods, commas to spaces, n1 again). Spaces inside a name are never removed, so anchor G stays
   "different". Per grantee and owner pair: exact normalized, normalization match (with rule id), different, or not
   comparable (either name absent). Address A1: street line equal after N1 and the first five ZIP digits equal; differs;
   absent. Line 2 is reported apart.
5. New caveat codes: `name_match_not_identity` (a string comparison, never "same party"), `most_recent_by_recorded`,
   `deed_not_sale` (amount 0), `multi_lot_deed`, `tied_deeds`, `snapshots_differ` (ACRIS 2026-05-31, HPD 2026-05-29,
   no newer inferred), `no_deed_found`. Mail drops: general caveat only (a shared address may be a mail drop and is not
   evidence); no per-pair flag in this slice (decided 2026-11-23).
6. Person names show only with the role they were recorded in.

## Agent wiring (mirrors Q2)

- `watchline/agent/tools.py`: `deed_vs_owner` tool with the same statuses and error wrapper, output capped with a caveat.
- `watchline/agent/answer.py`: `Kind` `ownership_comparison`, `Section`s `deeds` and `comparison`; the numbers guard
  accepts document ids, amounts and dates from the tool result.
- `watchline/agent/agent.py` and the system prompt: when to call this tool versus `registered_owner`; never say "same
  owner" or "the owner" on a name match.
- `watchline/ui/fixtures.py`: one fixture for `?fixtures=1`; generic renderer. Add the Q3 sample queries to `watchline/ui/samples.py`.

## Tests and evals

- `tests/test_deeds.py` (fast, fake graph): single deed, ties, no deed, multi-lot deed, amount 0, several grantees,
  absent names and addresses, the N1/N2/different/not-comparable table, A1 same/differs/absent, unresolved address.
- Tool tests in `tests/test_agent_tools.py`; kind, section and numbers guard in `tests/test_answer.py`.
- Live tool-level evals `tests/evals/q03_cases.yaml`: anchor A (exact), anchor G (one-space difference), a tied-deed lot,
  a lot with no deed, a no-HPD-building lot. Every expected value comes from a live probe first (CLAUDE.md).
- Agent evals `tests/evals/agent_q03_cases.yaml`: exact match reported with the caveat and not as "same party"; anchor G's
  difference not resolved; a $0 latest deed not called a sale; "who owns it?" not answered from the deed alone; tied deeds
  all listed. Three runs. Q1 and Q2 evals must still pass.

## Out of scope

Near-match scoring (Q22), DOS entities (Q5), grantor history, managing agents (Q4), per-kind UI layout, web search.
The Q2 follow-ups listed in `docs/status.md` stay open.

## Verification

1. Probe anchor G, a tied lot and a no-deed lot live, then write the expectations.
2. `make check`, `make test`, `make test-live`, `make eval`. EXPLAIN the new queries (index seek on the lot, no scans).
3. Worst-case lot (many deeds) answers in about a second.
4. `make eval-agent` (three runs), `make chat` by hand on anchors A and G, `make ui` fixture.
5. Fresh-context review (`/code-review`), fix findings, update `docs/status.md`, small commits on `q3-deed-vs-owner`.

## What was built (deviations from the plan above)

- `watchline/deeds/names.py` (N1, N2, A1) and `watchline/deeds/deeds.py`. `Neo4jDeedGraph` subclasses `Neo4jRegistrationGraph`, so `connect()` still
  returns five values and one object serves both tools; the deed tool is offered only when that graph has a `deeds` method.
- Address agreement is `absent` when either side lacks its street line or its ZIP (the spec leaves a missing ZIP open).
- Q2's tool output is unchanged: the owner address fields live on `RegisteredOwner` and show only in the Q3 output. Q3 drops Q2's
  `registration_period` and `owner_not_other_roles` caveats (they are about dates and roles it does not show).
- Each comparison pair carries both sides' addresses, so pairs that differ only by address (anchor D has three owner records) can be told apart.
- Tool output keys: `deeds`, `owners`, `comparison` (answer sections of the same names; an empty `deeds` list is evidence of "no deed").
- Evals: 7 tool-level cases (`q03_cases.yaml`, pass live) and 8 agent-level cases (`agent_q03_cases.yaml`) with a judge calibration.
  The LLM judge is now off by default for Q1, Q2 and Q3 because it is the costly part: `EVAL_JUDGE=1 make eval-agent` turns it on.
  The shared HEDGE pattern in `test_agent_eval_q01.py` also accepts "show, establish, prove, indicate".
- Live checks: EXPLAIN is two `NodeUniqueIndexSeek` and no scans. The lot with the most deeds (102 West 57 Street, 31,299 deeds) reads in 0.03 s.
