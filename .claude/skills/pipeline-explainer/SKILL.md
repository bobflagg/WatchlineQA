---
name: pipeline-explainer
description: Build an interactive, annotated explainer for a multi-stage algorithm or data pipeline, published as an Artifact. It has a clickable SVG map, a drill-down panel with an Annotation tab, an optional Release evidence tab (real rows from a checksummed release) and a Code tab (verbatim code pinned to a git commit), a second view for the decision logic, and optional worked-example widgets (score waterfalls, pass/fail checklists). Use when asked to explain, document or present how a pipeline or algorithm works, to make an "annotated diagram" or "pipeline map", or to reproduce the Landlord Resolution Pipeline artifact for another codebase.
---

# Pipeline explainer

Turns a real codebase's pipeline into one page a smart non-author can read and a technical reader can
check. Every claim on the page should be traceable to code or to a number you ran. The builder enforces
the mechanical half of that (verbatim, commit-pinned code; valid references); you enforce the rest.

Three finished examples live in `examples/`: `nlr-pipeline/spec.json` (a linear scoring pipeline with a
waterfall widget), `bor-ownership/spec.json` (a two-track pipeline with a pass/fail checklist widget) and
`owner-review/spec.json` (an LLM-agent pipeline with an escalation loop, a human branch, and a worked pair
taken from the agent's own output). Copy the closest one and edit it. `nlr-pipeline` and `bor-ownership` also carry a Release evidence tab on every box (see `releases` and `evidence` in the spec format): use it when the pipeline publishes a frozen, checksummed dataset. `references/spec-format.md` documents every field.

## When to use it, and when not

Use it for a pipeline with roughly 6 to 12 stages where the interesting part is how stages combine and
where the weak spot is. Do not use it for a single function, a tutorial, an API reference, or a status
report. For a one-off diagram with no code behind it, make a plain artifact instead.

## Process

1. **Scope.** Name the pipeline, the reader, and the single question the page answers. Decide what is
   private. Artifacts are private by default, but links to a private repo will not open for other
   people, and work the user has not released must not appear.
2. **Read the code in execution order.** Read the modules, not just the README. List each stage with its
   constants, guards and known weak points. Find the one decision rule that most readers will ask about,
   and the stage with the weakest evidence. Mark that stage `warn`.
3. **Trace one real example.** Run one real case through the real code or data (a notebook or script) and
   record the numbers at each stage. If the pipeline includes an LLM agent, use the agent's own saved output
   for the example (its verdict, evidence items, flags and timing) and the project's scoring files for the
   measured figures. Every number in `nums` comes from a run you did. Re-run to confirm
   before you quote it. If a number could not be verified, leave it out.
4. **Gather the evidence.** Collect measured results with sample sizes and intervals from the project's
   own evaluation. Mark results that are provisional, post hoc or exploratory as such, in the same box.
   Say what is not measured (for example recall).
5. **Design two views.** A pipeline map (stages in order, side inputs, parallel tracks) and a decision
   flowchart for one object (yes/no branches ending in outcomes). Keep each view to 12 boxes or fewer.
   Box kinds: `det` rule, `ml` learned model, `warn` lower-confidence stage, `io` data or no-join outcome,
   `rem` result. Use `flow` layout for a linear pipeline and `manual` for anything with branches.
6. **Write each box** with the fixed schema: `lede` (one or two sentences), `what` (3 to 4 verifiable
   bullets), `nums` (the example), `measured`, `open`, plus `code`. Plain, direct sentences. Say what the
   code does and nothing it does not. Put limits in `open`, not in the lede.
7. **Choose snippets.** 5 to 20 contiguous lines each, 1 to 4 per box, from a commit that is on a remote
   (`git rev-parse HEAD` after pushing). Locate them by `start` text and `count`, not by line number. Prefer the lines that make the claim checkable: the constant, the
   filter, the merge condition. Use notebook `lines` excerpts for how the example was run.
8. **Build and check.**
   ```bash
   python3 ~/.claude/skills/pipeline-explainer/scripts/build.py spec.json out.html --local preview.html
   ```
   Fix every error and read every warning. Then open `preview.html` in the Browser pane and run
   `scripts/browser_checks.js` (see `references/verification.md`). Look at each view once.
9. **Publish** `out.html` with the Artifact tool (it is a fragment: do not add `<html>` or `<body>`).
   Pass a short generic `icon` and a one-sentence `description` on the first publish. Update by
   publishing the same file path. Tell the user the link, that it is private until they share it, and
   which figures are provisional.
10. **Maintain.** Pins go stale as the code moves. Rebuild after meaningful changes, and re-verify any
    number that depends on the data.

## Rules that keep it honest

- Verbatim code only. Never retype a snippet. The builder takes it from `git show SHA:path`.
- A shared company, address or name is a hint, not proof. Say what each signal can and cannot show.
- Do not call an absence of a link evidence that two things differ.
- Measured, exploratory and provisional are different. Label them in the box that quotes the number.
- Name individuals only when the example needs it and the record is public. Prefer the entity or the id.
- Do not present a label set as independent review when it is not. State who labeled it.

## Pitfalls we hit

- In zsh, `git show $SHA:path` is parsed as a modifier. Write `git show "${SHA}:path"`.
- A hash-only navigation does not reload the page. Add `?v=N` when re-opening a rebuilt preview.
- If the Browser pane is hidden, the viewport reads 0 wide and screenshots time out. Show the pane, or
  use `resize_window`, then check again.
- SVG markers defined in a hidden SVG do not render. The builder gives each view its own marker.
- External stylesheets other than Google Fonts are blocked, so highlight.js loads from cdnjs and its
  token colors are inline in the template. Do not add a theme stylesheet.
- Only a plain `#token` reaches the page. Deep links look like `#node` and `#node-code`.
- Wide code makes readers scroll. The template wraps lines with a hanging indent and widens the panel on
  the Code tab. Keep snippets to 100 columns or fewer where you can.
- Box titles over about 38 characters overflow a 300px box. The builder estimates this and warns.
- A commit that is only local gives dead GitHub links. Push the branch, or pin a pushed commit, before
  you rely on the links. For a private repo the links open only for people with access.
- An evaluation against one person's labels is not independent, and a codebook tuned on the same cases
  inflates agreement. Say both in the box that quotes the figure.

## Files

- `scripts/build.py`: spec to page. Stdlib only. Validates and extracts the pinned code.
- `scripts/browser_checks.js`: paste into the Browser pane's `javascript_tool` on the built page.
- `assets/template.html`: page shell, styles and behavior. Edit it to change every explainer at once.
- `references/spec-format.md`: the spec, field by field.
- `references/verification.md`: static and browser checks, and what each one catches.
- `references/publishing.md`: how to publish and update, and what the viewer allows.
- `examples/`: two complete specs.
