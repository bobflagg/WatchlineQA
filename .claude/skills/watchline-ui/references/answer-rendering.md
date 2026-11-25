# Rendering the answer contract

DRAFT. This is a starting convention. The contract itself is defined in code (first version comes with the
building-profile slice). When the contract changes, update this file.

An answer has: a summary, facts with their evidence, caveats, sources and a `kind`.

## Order on the page
1. **Summary**: one or two plain sentences, as the chat message.
2. **Facts**: shaped by `kind` (profile card, list or table, comparison, network). Each fact that is a lead
   carries a Lead label.
3. **Caveat line**: if the answer contains any lead, one visible line under the facts, for example "Leads from
   name and address matches. Not findings of common ownership."
4. **Evidence expander** (collapsed): "Evidence: what this answer rests on".
   - **Sources**: graph records used (ids, run or release where relevant).
   - **Caveats**: every caveat attached to the answer, "what the record does and does not establish".
   - **Web sources**: labelled "lower confidence, context only, never identity evidence".

## Labels
- **Lead**: warning colors, small pill. Used for networks, portfolios, landlord links, name and address
  matches, DOS entity matches, mail-drop or masked addresses.
- **Recorded finding**: danger colors. Only for what the record states as a finding (for example a harassment
  finding after inquest or trial).
- **Record**: neutral. Violations, complaints and cases are what was cited, reported or brought, not
  findings of fault. Show counts by class or type, never a combined severity score.

## Kinds added for the report slices
All kinds use the one generic renderer today (summary, facts, caveat line, Evidence expander). A kind-specific renderer may change the
layout of the facts but may not drop a caveat, a lead label or the evidence tags. Each fact's evidence tag names its section.

- **`registration`** (Q2): per building, its registrations with last-registered and end dates, and the owner contacts as recorded.
- **`ownership_comparison`** (Q3): the latest deed(s), the grantees, the owners, and name and address agreement as two separate
  fields. Agreement is a Lead pill, never "same owner".
- **`timeline`** (Q12.1): a table of deeds, newest recorded first: recorded date, type, amount, grantors, grantees, and a "Not a sale"
  tag on amount 0 and on CORRD or CONDEED deeds. Above it, the counts as separate figures ("Deeds", "Not a sale"), never a
  combined number. A multi-lot deed shows "also names N other lots". Show at most a few names per party with "N rows recorded" for
  the rest. Evidence sections: `timeline` (the list) and `timeline_counts`.
- **`contacts`** (Q4): one row per contact with its recorded role and title, shown as "Name, as Managing Agent". A
  person never appears without the role. Roles are Record, not Lead. A shared business address shows a Lead pill with the note that
  it is not evidence of identity.
- **`violations`** (Q15): per building, counts by class (A, B, C, I) and status (Open, Close) with the oldest open inspection date, then the rate
  as figures (open violations, the lot's residential units, per unit), always with the same figure for each class beside the pooled one, or "rate unavailable". These are Record, never Lead. Never add
  classes into one number or colour by severity. Evidence sections: `violations`, `violations_rate`.
- **`litigation`** (Q28): a table of cases (type, opened, status, finding with its date, penalty, respondent as recorded). A harassment finding
  (After Inquest or After Trial only) uses the Recorded finding style; "No Harassment" and no finding are plain Record. A respondent that matches
  an owner name shows a Lead pill and never reads "the owner". Above the table, counts by type, status and finding as separate figures.
  Evidence sections: `cases`, `case_counts`.
- **`entities`** (Q5, PESP step 5): one fact per owner or grantee name looked up in the New York DOS active-entity snapshot. A name with a record is a Lead (the same name,
  never proof of the same party) and shows the DOS id, type, filing date, where the state forwards legal papers, the registered agent if listed, and how many entities share that address. A name
  without a record says "no record in the snapshot", never "does not exist". Individuals are not looked up, and the section says how many were left out. The process name is where service goes,
  not who runs the entity; a person's name there is shown only with that role. Evidence section: `dos_records`.
- **`identity_checkpoint`** (Q22 and Q7 with the Q9 effect; design in `docs/plans/identity-checkpoint.md`): built from templates, no model. One
  fact per candidate link, saying how the two parties are linked and its state: a lead awaiting the researcher's decision, accepted or
  rejected by the researcher (with the role, date and note), already joined by the method, or unsupported. One fact for the portfolio effect:
  the footprint as held in the graph next to the footprint after the researcher's decisions, always both, each as lots and residential
  units. An accepted link is labelled the researcher's inference, never a finding. Evidence sections: `links`, `portfolio_effect`,
  `decisions`. Today it uses the generic renderer. Planned: each link as a Lead card with its evidence (each item marked Used or Set aside),
  a state pill (Awaiting decision, Accepted, Rejected), and a before and after counts strip. Decisions are read from the report's JSON log;
  the page does not write them yet.

## Names and people
Show a person's name only with the role it was recorded in, and only in the answer that needs it.

## Fallback
If a `kind` has no renderer, render the markdown fallback and still show the caveat line and the Evidence
expander. A renderer may not drop caveats.
