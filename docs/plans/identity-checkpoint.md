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
4. Each link is judged on its own evidence. Accepting one never accepts another.

## Representation

**Link** (one candidate join between two landlord records; built by code from graph rows):
- `linkId`: a stable key made of the two names as recorded and the evidence kind, for example `BAHUMI|BADHUMI|address`. Never a
  run-local id.
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

## Open questions (for you)
- Should a rejected identity-basis link be allowed at all in the demo, or only address and name leads?
- Where does the decision log live between sessions: in the report file only, or a small local store?
- Q7's "used or set aside" wording: this note uses `setAside` per evidence item. Is that the vocabulary you want on the slide?
- The 2020 deed on the BADHUMI lot names `2141 WASHINGTON LLC` as grantee. Whether that name appears in the BAHUMI records is not
  probed; it would be a separate lead, and it is not part of this slice unless you want it.
