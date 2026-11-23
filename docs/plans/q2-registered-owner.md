# Slice: Q2, HPD-registered owner and registration dates

Intent: Q2 (`specs/questions/q02.md`, Q2.1 and Q2.2). Type an address, get each HPD registration on the
addressed lot's buildings: registration id, last-registered and end dates, and the owner contacts as recorded.
Status: module and fast tests done (live tests written); agent wiring in progress. Branch: `q2-registered-owner`.

## Checked live (2026-11-23)

- `(Building)-[hr:HAS_REGISTRATION]->(Registration {registrationId:int})-[:HAS_CONTACT]->(Contact)`.
- Dates are on the relationship `hr` (`lastRegistered`, `registrationEnd`, strings `YYYY-MM-DD`), so they belong to the
  building-registration pair, as the spec requires. The `Registration` node carries only the id.
- `Contact`: `contactType`, `corporationName`, `personName`, `contactKey`. Owner types: `CorporateOwner`
  (112,138; 183 blank), `IndividualOwner` (47,696; 206 blank), `JointOwner` (43,970; 1 blank). Name = `corporationName`,
  else `personName` (5 CorporateOwner have only `personName`). Other types (Agent, HeadOfficer, SiteManager...) are not owners.
- Placeholder registration id 0 is not in the graph (already excluded at load), so no filter is needed. Confirm the
  excluded-and-counted note in the caveat text only if the spec requires it (it says "counted"; the loader did that).
- Anchors seen: A BIN `3014788` reg 316103 (5413 PLAZA LLC, 2025-09-30, ends 2026-09-01); D BINs `3324448`/`3324450`/`3324451`
  regs 302437/344220/331116, owner spelled with and without a trailing period.
## Probe results (live, 2026-11-23)

- Dates are Cypher `DATE` values on `hr`, not strings (compare with `date('2026-05-29')`). 201,763 pairs: 3,230 have no
  `lastRegistered`, 8 have no `registrationEnd` (null, already applied by the loader). Ended before 2026-05-29: 51,057
  (the spec says 51,713; unexplained snapshot difference, no effect on the tool).
- No duplicate (building, registration) pairs, so the "rows disagree on a date" branch does not exist. Drop it from the design.
- Anchor C (BIN 3013901): reg 350423, `438 52 ST OWNERS CORP`, 2025-10-23, ends 2026-09-01.
- Anchor D: BINs 3324448, 3324450, 3324451, one registration each (302437, 344220, 331116), all 2025-07-16, ends 2026-09-01.
- Ended: BBL 3008210019, BIN 3014490, reg 306882, last 2020-08-31, ended 2021-09-01.
- No registration: BBL 3008970014 has `hpdRegistered` false and no buildings in the graph. The answer is "no HPD building
  recorded for this lot", which is the existing `no_hpd_building` situation, not only a missing registration.
- Several owners: reg 121720 (BIN 1060822) has two CorporateOwner contacts, `HP PLAZA LLC` and `HP PLAZA LP`. All listed.
- Several registrations: BIN 5014747 has regs 11009 (no owner contact, no `lastRegistered`, ends 2025-09-01) and 11065
  (IndividualOwner `Mirsad Skretovic`, 2026-01-08, ends 2026-09-01). Covers no-owner and null-date cases in one building.
- Exact duplicate owner contacts: 2 groups (max 2). Blank-name owner contacts: 390 (206 individual, 183 corporate, 1 joint),
  one per registration; spec says 422, not reproduced.
- Name rule confirmed: `coalesce(corporationName, personName)`.
- EXPLAIN done on both queries (2026-11-23): NodeUniqueIndexSeek on the lot, then Expand; no scans, Cartesian products or Eager.

## What already exists (reuse)

- `resolve_text` / `Answer` / `Match` in `watchline/geosupport/resolution.py`: address to BBL/BIN. Same borough and ambiguity handling.
- `ProfileGraph` protocol and `Neo4jProfileGraph._read` (read-only, timeout, `LIMIT`) in `watchline/profile/profile.py`.
- `Caveat` / `CaveatTemplate`, the resolution caveats (`_match_caveats`, `_unresolved_caveat`) and `HPD` source constant.
- Tool pattern in `watchline/agent/tools.py` (`make_building_profile_tool`, `ERROR_CAVEAT`, the "every failure is an answer" wrapper).
- Answer contract in `watchline/agent/answer.py` (`assemble` copies evidence and caveats from tool results).

## Design

New package `watchline/registration/` with `registered_owners(client, graph, rg, text, **kw) -> Registrations`.

1. Resolve with `resolve_text`. If not resolved, or the BBL is not in the graph, return the resolution and its caveat only. Never guess a lot.
2. One parameterized read on `RegistrationGraph.registrations(bbl)`: per building of the lot, its registrations with `hr` dates.
   One read for owner contacts: `contactType IN [owner types]`, grouped by registration id. Both `LIMIT`ed; truncation sets the
   existing `truncated` caveat.
3. Build per building: `bin`, `address`, `addressed`, `registrations: [{registrationId, lastRegistered, registrationEnd,
   owners: [{contactType, name}]}]`. Rules from the spec:
   - All registrations listed, none chosen. Empty list means "no HPD registration recorded", not "no owner".
   - Owner contacts: all three owner types, names exactly as recorded, exact duplicates (same type and name) collapsed,
     blank name kept with name absent. No owners means empty list; nothing inferred.
   - Dates: null stays absent. (No pair has disagreeing rows; see probe results.)
   - Whether a registration is current is not computed in the data. Add `ended_before_snapshot` only if the spec's "agent states
     it against 2026-05-29" is better done in code; default: put the snapshot date in the caveat and let the model compare.
4. Caveats (new codes, as `Caveat` constants): `registrant_not_title` (registrant, not proof of title), `registration_period`
   (period end given, no start; snapshot date 2026-05-29), `owner_not_other_roles` (not the deed grantee, a process contact
   or the managing agent). Plus the resolution caveats. A lot with no registration gets `no_registration_found`.
5. Source: reuse `HPD`.

## Agent wiring

- `watchline/agent/tools.py`: `make_registered_owner_tool` mirroring the profile tool (`needs_borough`, `invalid_input`, `error`
  statuses), and `registered_owner_to_dict`. Cap buildings at `MAX_BUILDINGS_OUT` with the `buildings_capped` caveat.
- `watchline/agent/agent.py`: add the tool to `create_deep_agent(tools=[...])`; `build_agent` gets the new graph handle.
- `watchline/agent/answer.py`: add `Kind` value `registration`; add `Section` value `registrations`; teach `_resolve` to find it
  (by BIN, or whole list for an absence), `_SECTION_KEY`, and `ModelAnswer.kind` description. `ungrounded_numbers` must treat
  registration ids and dates in tool data as grounded (check `_candidate_counts` / `_data_only`).
- `watchline/agent/prompts/`: system-prompt lines on when to call which tool (owner or registration questions vs profile) and the
  rule not to call a registrant "the owner of the building". `ontology_rules.md` is unchanged (it already says registrations are
  not deeds); only add if a rule is missing.
- `watchline/ui/render.py` and `fixtures.py`: generic renderer should already show the new kind; add one fixture so `?fixtures=1`
  previews it. No per-kind layout (waits for the UI slice).

## Tests and evals

- `tests/test_registration.py` (fast, fake graph): single registration; several per building; none; no owner contact; blank
  name; duplicate contacts collapsed; non-owner types excluded; joint owners; date-disagreement branch; unresolved address
  returns resolution only; truncation caveat.
- `tests/test_agent_tools.py`: tool statuses and caveats, mirroring the profile tool tests.
- `tests/test_answer.py`: the new kind and section resolve; numbers guard accepts ids and dates from the tool result.
- Live (`make test-live`) and `tests/evals/q02_cases.yaml` (`make eval`): anchors A, C, D, the ended case, the no-registration
  case, a multi-registration BIN, joint owners. Expectations come only from live probes, not from the spec's provisional values.
- Agent evals `tests/evals/agent_q02_cases.yaml` (`make eval-agent`): an owner question gets the registrant with the caveat;
  "who owns this building?" is not answered as title; an ended registration is not presented as current; no registration infers
  no owner; a follow-up from a profile answer; a trap asking for the managing agent (Q4, out of scope: refusal or honest limit).
  Existing 12 Q1 evals must still pass.

## Out of scope

Managing agents, officers, site managers (Q4), deed grantee compare (Q3), DOS records (Q5), staleness across the whole city (Q17),
per-kind UI layout, web search.

## Verification

1. `make check`; `make test`.
2. Live probes first (list above), then `make test-live` and `make eval` with live anchors.
3. EXPLAIN the two new queries; worst-case lot (many buildings) answers in about a second.
4. `make eval-agent` (Q1 plus Q2 cases, three runs) and `make chat` by hand on anchors A, D and an ended registration; `make ui` check of the new fixture.
5. Fresh-context review (`/code-review`), fix findings, update `docs/status.md`, merge, small commits on branch `q2-registered-owner`.
