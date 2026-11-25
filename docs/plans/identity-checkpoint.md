# Slice C design note: the identity checkpoint (Q22 and Q7, with the Q9 effect)

Status: design only, 2026-11-25. Nothing is built. Read with `docs/plans/report-graph.md` ("Two layers").

## What the demo needs
Show the portfolio of `YONATAN BAHUMI`, show that `YONATAN BADHUMI` is linked to it only by a shared business address, let the
researcher accept or reject that link, and show the portfolio change. Probed 2026-11-25 (by landlord name, never by id):

| | Lots | Residential units |
|---|---|---|
| Portfolio as the graph holds it (BAHUMI covers) | 55 | 176 |
| BADHUMI covers (lot 2030370098, no overlap with the 55) | 1 | 3 |
| If the link is accepted | 56 | 179 |

The link is `CONNECTED_BY_ADDRESS` (3 edges, weight 5.44, in operational group `ON-116395`). Group and edge ids are run-local, so they
appear in evidence only with the run, and never on a slide.

## Principles
1. A decision is an input to the report, not a write to the graph. The graph and its snapshot never change; the section function
   takes the decisions as an argument.
2. The section function is pure: same graph snapshot and same decisions give the same section, byte for byte. No LLM.
3. A name or address match stays a lead until the researcher decides. An accepted link is the researcher's own inference, shown as
   such, with the evidence beside it. It is never restated as a graph finding.
4. One link and one decision per pair of parties. The link carries every kind of evidence (address, name, shared registration) and the researcher
   judges the pair on all of it (changed 2026-11-25; before, each kind was its own link). Accepting one pair never accepts another.

## Representation

**Link** (one candidate join between two landlord records; built by code from graph rows):
- `linkId`: a stable key made of the two party names as recorded, for example `YONATAN BAHUMI|YONATAN BADHUMI` (a lot suffix or `#n` only to tell
  two same-named parties apart). Never a run-local id. `kinds` lists how the pair is joined (address, name, contact, identity).
- `a`, `b`: the two records (name as recorded, role, number of lots covered).
- `evidence`: list of items, each `{kind: shared_address | name_similarity | identity_edge | shared_contact, text, source, setAside}`.
  `setAside` is true and the reason is given when the address is masked or on the mail-drop list (Q6); a set-aside item supports
  nothing.
- `basis`: how the graph holds it: `identity` (an identity edge exists) or `lead` (address or name only).
- `rule`: the named Q22 rule when names are compared (N1, N2, S1, L1, AB1), or none.
- `state`: `awaiting`, `accepted` or `rejected`.

**Decision input** (a plain list, passed in, saved with the report):
`{linkId, decision: accept | reject, decidedBy (role, not a name), decidedAt, note}`. Unknown link ids are reported, not ignored. A
second decision on the same link replaces the first and both stay in the log.

**Section output** (`kind: identity_checkpoint`, sections `links`, `decisions`, `portfolio_effect`):
- `links`: every link with its state. Links with basis `identity` start as `accepted_by_method` (the graph already joined them) and can
  be rejected, so the report shows what a rejection would remove.
- `decisions`: the decisions as recorded, echoed in order.
- `portfolio_effect`: the portfolio recomputed twice and shown side by side, each labelled with the decisions it assumes:
  `as_held` (graph only: lots, units, landlord records) and `as_decided` (the same after applying the decisions). Lots are the distinct
  lots covered; units come from the lots, never from a building. A lot reached by two accepted links is counted once. Counts are not
  summed into a score.
- Caveat codes: `link_is_lead` (while any link awaits), `researcher_decision` (when any decision applies, text says it is the
  researcher's inference), `shared_address_not_evidence`, `name_match_not_identity`, `portfolio_run_local`, plus the masked or
  mail-drop codes when set-aside evidence exists.

## How the count and evidence change
- `awaiting`: `as_decided` equals `as_held` and the link is listed as a lead. This is the first thing the audience sees (55 lots, 176 units).
- `accepted`: the other record's lots join (56 lots, 179 units here). The link's evidence moves up and is labelled "accepted by the
  researcher". Its caveat stays visible.
- `rejected`: the portfolio stays at `as_held` and the link shows as rejected with the note. A rejection of an identity-basis link
  removes the lots only that link reached.
- Evidence for and against (Q22): "for" is the shared non-masked address and any similarity rule; "against" is that names differ and no
  joining record other than the address exists; "unresolved" is stated explicitly.

## Reproducibility
- Inputs recorded in the report: graph snapshot (HPD and ACRIS dates, BOR run) and the decision list. Same inputs give the same sections.
- The portfolio recomputation is a pure function of graph rows plus decisions, so it is unit-tested with fake rows and needs no model.
- Ordering is fixed (links by `linkId`, lots by BBL), so a snapshot test compares exactly.
- The LangGraph checkpoint step (`interrupt()`) only collects the decision. The same decision list given to the section function
  reproduces the report without the graph runner.

## Build order inside Slice C
1. `links` and `portfolio_effect` as a pure function over rows, with the decision list as an argument (tests with fake rows).
2. The graph reads: landlord records by name, their covered lots and units, their address and identity edges, mask and mail-drop flags.
3. Contract wiring and UI (kind `identity_checkpoint`, rendered per `.claude/skills/watchline-ui/references/answer-rendering.md`).
4. The LangGraph checkpoint (later, with the report graph).

## Tests (no model calls)
- Fake-row unit tests: awaiting, accepted, rejected, a lot reached twice, a masked-address link (set aside), an unknown link id, a
  replaced decision, determinism (same input twice gives identical output).
- Live fixture, looked up by landlord name: BAHUMI 55 lots and 176 units, BADHUMI 1 lot and 3 units, accepted gives 56 and 179.
- Berkovics as the contrast: records joined by identity edges, so `accepted_by_method`. Probe its numbers before writing expectations.

## Decisions (2026-11-25, from the open questions)
- **Rejecting identity-basis links.** Build it so any link can be accepted or rejected. The demo uses only the BADHUMI address lead. A rejection
  of an identity-basis link overrides a method decision, so the report labels it as the researcher's decision. Berkovics shows the
  identity-basis case read-only, as "already joined by the method".
- **Decision log.** In the report file only, as a JSON list saved next to the report. The LangGraph checkpointer holds in-progress state
  during a run, nothing more. The same file reproduces the report without a graph runner, and serves the backup run before the talk. Revisit
  a local store only if the report becomes a multi-session product.
- **Vocabulary.** The field stays `setAside` (Q7's "used or set aside"). On the page the labels are "Used" and "Set aside", with the reason
  (masked address, mail-drop list). "Rejected" is reserved for the researcher's decision on a link, never for evidence.
- **`2141 WASHINGTON LLC`.** Not part of this slice. It is a 2020 grantee on the BADHUMI lot, a lead between a deed and the HPD owners, not a link
  between landlord records. Before the demo, run `deed_vs_owner` on 2141 Washington Avenue (no model) to see what it shows. If the name appears
  in the BAHUMI records it becomes a second checkpoint candidate. Not yet probed.

## Step 2 findings (2026-11-25, `watchline/identity/graph.py`)
- A party is a closure of landlord records joined by `CONNECTED_BY_IDENTITY`, so identity joins sit inside a party (shown as `records`), and links are
  only name and address leads. Identity-basis links as designed therefore do not occur with this reading; the "reject an identity link" path in
  `checkpoint.py` stays available but unused until a source of identity-basis links is chosen.
- BAHUMI: 6 records, 55 lots, 176 units. The BADHUMI record is linked to 3 of the 6 by `CONNECTED_BY_ADDRESS` (one link, address as recorded
  `4058 BRONX BOULEVARD 1B, Bronx, NY 10466`, not masked or on the mail-drop list). Accepting it gives 56 lots and 179 units, as designed.
- BERKOVICS: the identity group around `MOSES BERKOVICS` holds 8 records under three recorded names (`ALBERT LABOZ`, `AMNON SHALHOV`,
  `MOSES BERKOVICS`): 48 lots, 1,628 units. That is more than the "six records" in the working choice. Decide before the demo whether it is
  still the contrast case, and check the three names by hand.
- Masks and the mail-drop list are matched on the address as spelled (street line and ZIP); the party, link and mask caveats say so.
- Deed-only landlord links (`CONNECTED_BY_DEED`) are not read, with a caveat.

## Step 4 (2026-11-25, `watchline/report/graph.py`)
- LangGraph `propose` -> `decide` (the only `interrupt()`) -> `finish`. State is plain JSON, so any checkpointer can hold it; tests use `InMemorySaver`.
- The pause payload carries the leads awaiting a decision, the portfolio as held and as decided, the caveats and the expected answer shape. A bad
  answer goes back to the same pause with the reason in `error`. `decidedAt` comes from the caller, not the clock.
- Resume re-runs only the pausing node: the graph is not read again until `finish` (tested by counting reads).
- The result holds the Answer and the decision log text. The same log on the same snapshot reproduces the Answer through
  `identity_checkpoint(ig, name, decisions)` (tested: the graph's Answer equals the direct call's).
- A checkpointer in memory lasts for the process. For the demo, the saved decision log is the durable record.

## Shared-registration evidence (2026-11-25, `watchline/identity/graph.py`)
- Found by running `deed_vs_owner` on 2141 Washington Avenue: HPD registration 205148 of the BADHUMI lot lists `YONATAN BADHUMI` as HeadOfficer and
  `YONATAN BAHUMI` as Officer and Shareholder. Q22 counts "same registration" as a joining record, so the link was better supported than "a shared address only".
- New read `shared_registrations`: for each candidate party, the registrations of buildings on either party's lots that list a contact named like the
  anchor party and a contact named like the other (names upper-cased, as spelled; roles shown). One evidence item per registration, at most 10 per link.
  It strengthens candidates found by name or address edges; it does not discover new ones.
- It is its own link (`<anchor>|<other>|contact`), decided on its own evidence. `against` on the address link no longer says only an address joins the
  parties when a contact link exists for the same pair. New caveats: `shared_registration_not_identity` and `registration_names_as_recorded`.
- BAHUMI now shows two leads for BADHUMI (address and registration); accepting either gives 56 lots and 179 units. Berkovics gets one contact link
  (`MICHAEL MAKHARADZE`); not yet reviewed by hand. Possible follow-up: group the links of one pair under one decision for the demo.

## One decision per pair (2026-11-25)
- `Link.kinds` replaces `Link.kind`; `linkId` is the pair, with no kind. `build_inputs` builds one link per candidate party with the address, name and
  shared-registration evidence together, so BAHUMI and BADHUMI are one lead with two evidence items (address, registration 205148).
- `against` is computed from that link's own evidence, so "no joining record other than a shared address" appears only when the address is all there is.
- A link is usable if any of its evidence is usable: an address set aside as a mail drop does not make the pair unsupported when a registration lists both names.
- Berkovics now shows 11 possible links (one per candidate party). Decide before the demo whether that is the contrast you want.
