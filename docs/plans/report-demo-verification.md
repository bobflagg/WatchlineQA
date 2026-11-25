# Report demo verification (2026-11-25)

Every number in the two demo reports was checked against read-only Cypher run on the live graph, separate from the report code. The reports are saved in
`docs/demo/backup-runs/<address>/` (`report.md` and `decisions.json`); rebuilding either from its saved decision log (`make report ADDRESS=... DECISIONS=...`) gives a
byte-identical file. Decisions in these runs are rehearsal decisions (date 2026-12-01), not research findings. Re-check every number again before the talk: the graph snapshot may change.

| Item | 2141 Washington Avenue, Bronx (lot 2030370098) | 74 Clinton Place, Bronx (lot 2032070010) |
|---|---|---|
| PLUTO | built 1899, class C0, 3 units, assessed $59,040 | built 1901, class C0, 3 units, assessed $62,940 |
| HPD buildings (PLUTO count) | 1 (1) | 1 (1) |
| Registration | 205148, last registered 2025-07-08, ends 2026-09-01 | 216075, last registered 2024-10-23, ends 2025-09-01 |
| Registered owner as recorded | 2141 WASHINGTON AVE LLC | 74 CLINTON PLACE LLC |
| Deeds | 9; 7 with amount 0; 2 with an amount (549,855 recorded 2020-01-09; 453,900 recorded 2017-10-26); no correction deeds | 8; 5 with amount 0; 3 with an amount; latest recorded 2021-12-22 |
| Open violations by class | A 5, B 14, C 3 (22); oldest open inspection 2024-08-14; closed A 2, I 1 | A 1, B 7, C 7 (15); oldest open inspection 2015-05-11; closed A 1, B 2, I 1 |
| Rate per unit (pooled; by class) | 22 over 3 units = 7.333 (A 1.667, B 4.667, C 1) | 15 over 3 units = 5 (A 0.333, B 2.333, C 2.333) |
| Housing Court cases | none recorded | 8, all closed; one After Trial harassment finding (case 284822, opened 2016-05-24, finding 2016-07-25, penalty 5,200), respondent McLORD OBIOHA, no match with the owner name |
| Portfolio | anchor YONATAN BADHUMI: 1 lot, 3 units as held; accepting the lead for YONATAN BAHUMI gives 56 lots, 179 units | anchor YONATAN BAHUMI: 55 lots, 176 units (6 records) as held; accepting the lead for YONATAN BADHUMI gives 56 lots, 179 units |
| The lead | address 4058 BRONX BOULEVARD 1B and registration 205148, which lists BADHUMI as HeadOfficer and BAHUMI as Officer and Shareholder | the same pair, seen from the BAHUMI side |

## Still to check by hand before the talk
- The Public Advocate's 19 Bronx buildings against the 55 BAHUMI lots (working choice, `report-graph.md`), and the "Worst Landlords" list context, which is never shown as a graph answer.
- Whether the audience should see 74 Clinton Place's finding at all: it is a finding on a case at the building whose respondent is an individual, not a BAHUMI party and not the registered owner.
- The browser look of the report page (`make report-ui`) on both addresses.
