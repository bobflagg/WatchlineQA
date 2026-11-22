# Slice: address to building profile

Intent: Q1 (`specs/questions/q01.md`, sub-questions Q1.1 to Q1.4), extended with summaries of violations,
complaint problems and litigation. Type an address, get the lot, its buildings and those summaries, with caveats.

## What already exists

- `watchline/geosupport/resolution.py`: `resolve_text(client, graph, text)` returns an `Answer` with outcome,
  bbl, bin (the addressed building), `in_graph`, `related_lots`, candidates, grc and tried spellings. This is Q1.3.
- `Neo4jGraph` in the same file: read-only driver wrapper (`execute_query`, `RoutingControl.READ`). Reuse the pattern.

## Graph shape (checked live 2026-11-22)

- `(Lot)-[:HAS_BUILDING]->(Building)`; Building has `bin`, `address`.
- `(Building)-[:HAS_VIOLATION]->(Violation {violationClass, status, inspectionDate})`
- `(Building)-[:HAS_PROBLEM]->(Problem {majorCategory, minorCategory, problemType, status, receivedDate, duplicate})`
- `(Building)-[:HAS_LITIGATION]->(Litigation {caseType, caseStatus, harassmentFinding, caseOpenDate, penalty})`
- Lot properties: `unitsRes`, `assessedTotal`, `yearBuilt`, `buildingClass`, `plutoNumBuildings`, `hpdRegistered`.
- Violations, problems and litigation hang off Building, so they exist only for HPD-registered buildings.
- Example: lot `3008210012` (224 54 Street) has 3 BINs; `3324450` has 3 violations, `3324448` has none.
- The MCP `get_neo4j_schema` tool fails (APOC `sample: None` bug). Use `db.schema.*` procedures instead.

## Design

New package `watchline/profile/` with `building_profile(client, graph, text) -> Profile` (pure Python plus
three parameterized read queries). No agent wiring in this slice; the agent tool wraps this function later.

1. Resolve with `resolve_text`. If outcome is `ambiguous`, `not_found` or `unavailable`, or the BBL is not in
   the graph, return the resolution only, with its caveat. Never guess a lot.
2. Lot query: lot fields above. Lot-wide values stay on the lot, never copied to buildings.
3. Buildings query: all BINs on the lot, the addressed one flagged (`bin` from Geosupport). Report
   `buildingsListed` (HPD BINs) and `plutoNumBuildings` separately, each labelled by source.
4. Summary queries, per building, counted by class or type, never summed into a score:
   - violations by `violationClass` and `status`
   - problems by `majorCategory`, with `duplicate` handled explicitly (see open questions)
   - litigation by `caseType` and `caseStatus`; `harassmentFinding` reported as a count only for
     "After Inquest" or "After Trial", and described as "brought" otherwise
5. Caveats attached to the result (data, not prose in the code path):
   - always: violations, problems and litigation are what was cited, reported or brought, not findings of fault
   - always: unit count and assessed value are lot-wide
   - match was a variant or inferred; borough inferred from a neighborhood
   - lot not HPD-registered: "no building recorded in the HPD registrations", not "no buildings"
   - the two building counts differ
   - `related_lots` non-empty (condominium): other lots share the BIN
6. Tool conventions: parameterized, row-limited, timeout, `EXPLAIN` on each new query.

## Tests

- Unit (`make test`): fake `Graph` with canned rows; caveat selection per case; outcome short-circuits.
- Live (`make test-live`), anchors from q01: D (224 54 Street, 3 BINs, 18 units, PLUTO 3), A (5413 7 Avenue,
  1 BIN, 32 units), 17 Battery Place (PLUTO 2, HPD 1), one unregistered lot (BBL, no BIN, no summaries).
- `make check` before each commit. Small commits on a branch.

## Open questions

- Should `duplicate = true` problems be excluded from counts or shown as a separate count? (Recommend: count
  both, labelled, since the graph records the flag and dropping rows silently hides data.)
- Per-building or lot-level summaries by default? (Recommend: per building, with a lot total only as a sum of
  counts of the same type, not a severity score.)
- High-volume buildings: 4M problems in total. Check `PROFILE` db hits on the largest building before fixing
  the query shape.

## Out of scope

Agent and chat wiring, web search, deeds and ownership leads (separate slice, leads-not-findings rules apply),
explainer update (done after the first working slice per `docs/process.md`).

## Decisions made while building

- Duplicate problems are counted separately (key: major category plus the duplicate flag). Summaries are per building,
  with `lot_totals()` summing only same-type counts.
- Source snapshots (PLUTO 26v1, HPD through 2026-05-29, Geosupport 25b) are constants taken from `q01.md`; the graph
  does not carry them. Refresh them when the data is reloaded.
- The Geosupport reason code is not captured by `Result`, so the variant caveat reports the return code (GRC) and the
  returned address only.

## Review follow-up (fresh-context review of 37de83c)

Fixed: timeout now enforced with `neo4j.Query(timeout=...)`; early returns carry a reason caveat; variant caveat reports
the returned address and GRC, inferred and neighborhood caveats separate; harassment wording; counts and
characteristics labelled with unit and source; registered-but-no-building case; missing PLUTO count; addressed
building missing; truncation caveat; tests strengthened and a live unregistered-lot test added.

## EXPLAIN evidence (2026-11-22, anchor D)

All five queries start with `NodeUniqueIndexSeek` and expand from there. No `AllNodesScan`, `NodeByLabelScan`,
`CartesianProduct` or `Eager`. The three summary queries use `EagerAggregation` for `count(*)`, which is expected.
Worst-case building (16,771 problems): about 0.5 s.
