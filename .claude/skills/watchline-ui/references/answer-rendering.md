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

## Names and people
Show a person's name only with the role it was recorded in, and only in the answer that needs it.

## Fallback
If a `kind` has no renderer, render the markdown fallback and still show the caveat line and the Evidence
expander. A renderer may not drop caveats.
