# Who Owns What and Watchline: what each shows (checked 2026-11-25)

How this was checked: WoW's public API (`wow-django.herokuapp.com/api/address`) for the three sample lots, WoW's public source (`JustFixNYC/who-owns-what`, `portfoliograph/`),
and NYC Open Data (HPD violations `wvxf-dwi5`, HPD registration contacts `feu5-w2e2`, HPD litigations `59kj-x8nc`) queried for the same lots. Nothing was read from WoW's web pages (they are
a single-page app), so what its screens say beyond the API (disclaimers, wording) is **not verified**: look at the site by eye before claiming any difference on a slide.

## What WoW returns for the demo lots
- For both 2141 Washington Avenue and 74 Clinton Place it returns the **same portfolio: 56 buildings on 56 lots**, 179 residential units in all. Those are exactly the 56 lots Watchline reaches by
  accepting the BADHUMI lead (55 BAHUMI lots plus the BADHUMI lot). For 5413 7 Avenue it returns 2 buildings.
- Per building: registration id and dates, owner and business names, every contact with its role, total and open HPD violations, complaints (total and recent), residential units, year built,
  evictions, rent-stabilized units, tax-program flags, council district, and the last ACRIS sale (date and amount).
- The method, from WoW's own code: landlord contacts (name plus a business address standardized with Geosupport) become nodes; edges are added for similar names and for matching business
  addresses, with weights; connected components are the portfolios; a portfolio over 300 lots is split by Louvain community detection. That is the same construction as Watchline's operational network
  layer. WoW's API gives no evidence for why two buildings are in one portfolio.

## Where they agree (so no difference to claim)
- Portfolio membership for these lots (56 = 56, same lots), units (179), the last sale of 2141 Washington Avenue (549,855, document date 2019-12-24; Watchline lists it as recorded 2020-01-09),
  Housing Court cases for 74 Clinton Place and 5413 7 Avenue (8 and 4, matching HPD open data; Watchline also lists the harassment finding and the respondent).

## Where they differ, as found
1. **Watchline's violation counts are far lower than HPD's.** HPD open data holds 11,460,972 violations (2,931,892 open); the graph holds 1,901,592 (466,895 open), about one in six. By lot (open data, today, against
   the graph): 2141 Washington Avenue 180 total and 86 open against 25 and 22; 74 Clinton Place 379 and 152 against 19 and 15; 5413 7 Avenue 194 and 28 against 20 and 18. WoW's figures for 2141 Washington
   Avenue (180 total, 86 open) equal HPD's. Every violation of these lots in open data has the lot's building BIN, so this is not a BIN mismatch. The reason is not known (the loader is outside this repo).
   **The report's violation counts are a floor, not the HPD count, and a WoW-literate audience will see it at once.** Litigation, registrations and deeds were spot-checked and agree.
2. **WoW is current; the graph is a snapshot.** HPD's registration 205148 now shows a last-registered date of 2026-10-08 (Watchline's snapshot: 2025-07-08, snapshot 2026-05-29) and **every contact on it
   is spelled "Yonatan Bahumi", including the head officer, who is "YONATAN BADHUMI" in the snapshot**. In today's HPD data the misspelled record that is the demo's centerpiece would already be merged by
   name. The demo is a frozen snapshot with its dates printed, and the story holds only on that snapshot.
3. **Watchline shows what WoW's API does not:** the evidence behind each link (an address, a registration listing both names) with what argues against it, a decision by the researcher that is saved and changes the portfolio count,
   the whole deed history with grantors and grantees, harassment findings with the respondent compared with the owner name, the DOS entity records, caveats and sources on every section, and an export that rebuilds byte for byte.
4. **WoW shows what Watchline does not:** complaints, evictions, rent-stabilized units and tax-program flags, the map, and current data.

## What this means for the talk
- Do not say Watchline finds portfolios WoW cannot. For these lots the membership is the same. The claim that holds is about **what each says about a link**: WoW lists the buildings; Watchline shows why, lets a
  person decide, and keeps the decision with the evidence. Confirm in WoW's interface how it labels the portfolio before saying it presents the portfolio as fact.
- Do not show a violation count without the caveat above until the violations in the graph are complete.
