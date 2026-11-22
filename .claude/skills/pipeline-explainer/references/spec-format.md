# Spec format

One JSON file. The builder (`scripts/build.py`) reads it and writes the page. Paths in `repos` may start
with `~`. See `examples/*/spec.json` for complete files.

## Top level

| Field | Required | Meaning |
|---|---|---|
| `title` | yes | The artifact's name: a short noun phrase, two to four words. Becomes `<title>`. |
| `eyebrow` | yes | Small line above the heading, for example `Working map · repo-name`. |
| `heading` | yes | The page heading. |
| `intro` | yes | Two to four sentences: what the pipeline does, what the reader can do on the page, and the main caveat. |
| `repos` | if snippets | Map of repo key to `{path, sha, slug, label}`. See below. |
| `views` | yes | One or more maps. The first is shown by default. See below. |
| `nodes` | yes | Map of box id to its details. See below. |
| `snippets` | no | Map of snippet id to a code excerpt. See below. |
| `widgets` | no | Worked-example widgets a box can embed. See below. |
| `default_node` | no | Box shown first. Default is the first view's first box. |
| `labels` | no | Override panel text: `what`, `nums`, `measured`, `open`, `tab_note`, `tab_code`. |
| `kind_labels` | no | Override legend labels for `det`, `ml`, `warn`, `io`, `rem`. |
| `legend_extra` | no | Extra legend entries drawn as a dashed line: `[{"label": "Whole-city input"}]`. |
| `hint` | no | Replace the line under the map. Default names the pinned commits. |

## `repos`

```json
"repos": {"app": {"path": "~/code/app", "sha": "9842004", "slug": "owner/app", "label": "app"}}
```
`sha` can be any revision; the builder resolves it to a full hash. It warns if the commit is not on a
remote branch, because the GitHub permalinks would 404. `slug` is the GitHub `owner/name`. `label` is the
short name shown on links.

## `views`

Every view needs `id`, `label`, `layout`, `title` and `desc` (the last two are the SVG's accessible name),
and may set `default_node`.

### `layout: "flow"`: a vertical pipeline

```json
{"id": "pipe", "label": "Pipeline", "layout": "flow", "x": 190, "w": 300,
 "items": [{"id": "s1", "kind": "det", "title": "1 · Extract", "sub": "one record per name"},
           {"id": "s2", "kind": "ml", "title": "2 · Score", "sub": "match weight", "label_before": "pairs ≥ 0.5"}],
 "side": [{"id": "stats", "kind": "io", "title": ["City-wide", "statistics"], "x": 524, "w": 148,
           "span": ["s1", "s2"], "marks": [{"text": "name rarity", "to": "s2"}]}]}
```
Items stack top to bottom with arrows. Optional per item: `h` (box height, default 52), `gap_before`
(default 22), `label_before` (text on the arrow above), `lines` (several subtitle lines). A `side` box
spans the items from `span[0]` to `span[1]`, labels each `mark`, and draws a dashed arrow into the target.

### `layout: "manual"`: a flowchart or parallel tracks

```json
{"id": "decide", "label": "Decision", "layout": "manual", "width": 680, "height": 520,
 "nodes": [{"id": "q1", "kind": "det", "x": 40, "y": 24, "w": 300, "h": 50, "title": "Same key?", "sub": "blocking"}, ...],
 "edges": [{"from": "q1", "to": "q2", "label": "yes"},
           {"d": "M340 198 L370 198 L370 276 L398 276", "label": "no", "lx": 346, "ly": 192}],
 "labels": [{"text": "no", "x": 346, "y": 270}]}
```
An edge with `from` and `to` draws a straight connector: bottom to top if `to` is below and overlaps
horizontally, or right to left if `to` is to the right and overlaps vertically. Anything else needs an
explicit path `d`. Edge options: `label`, `lx`, `ly`, `dashed`, `arrow` (false for no arrowhead). Use
`labels` for free text such as the "no" beside a path.

Layout tips: a 680px-wide viewBox. A box 300px wide fits a title of about 38 characters and subtitles of
about 48. Leave 22 to 24px between stacked boxes so the arrow shows. Keep a decision column on the left and
outcomes on the right. Route "no" branches that skip boxes along a vertical bus rather than across boxes.

## `nodes`

```json
"s2": {"kind": "warn", "tag": "Lower confidence", "title": "2 · Merge pass", "ref": "path.py · function",
       "lede": "One or two sentences.", "what": ["bullet", "bullet"],
       "nums": [["5 → 1", "groups for the example"]],
       "measured": ["97% judged correct (150 pairs, 92 to 99%)."],
       "open": ["A known limit."], "code": ["merge_rule"], "widget": "worked"}
```
`kind`, `title`, `ref`, `lede`, `what` are required. `tag` defaults to the kind's legend label. `nums` is a
list of `[value, meaning]`, shown under `labels.nums`. `measured` shows in a green box, `open` in an amber
box. `code` lists snippet ids and enables the Code tab. `widget` embeds a widget. Ids are lowercase letters,
digits, `-` and `_`, and must not end in `-code`. Every box on a map needs an entry here, and the reverse.

## `snippets`

Line range, from git at the pinned commit:
```json
"merge_rule": {"repo": "app", "path": "src/merge.py", "a": 582, "b": 594, "lang": "python",
               "caption": "Merge same-name groups that share a company."}
```
`a` and `b` are 1-based and inclusive. The first and last lines must not be blank. Common indentation is
removed. Instead of line numbers you can locate the excerpt by its text, which survives edits above it:
`{"start": "def merge(", "count": 13}` (the matching line plus 12 more) or `{"start": "def merge(", "end": "    return out"}`
(through the first line that starts with `end`). `occurrence` picks the nth match of `start`. The builder
records the resolved line numbers, so the links and the gutter still show them. Languages that highlight.js handles in its default bundle work (`python`, `sql`, `javascript`,
`bash`, and others).

Exact lines, checked against the file (use for notebook cells):
```json
"run": {"repo": "app", "path": "demo.ipynb", "lang": "python", "caption": "How the example was run.",
        "lines": ["base = cluster(preds)", "final = merge(base)"]}
```
For `.ipynb` the lines are checked against code cells at the pinned commit. No line numbers are shown.

## `widgets`

A box embeds one widget by name; a widget has named cases the reader switches between.

Waterfall (a running total against a threshold):
```json
"worked": {"type": "waterfall", "title": "Worked pairs", "unit": "bits", "threshold": 9.97,
  "threshold_label": "the weight for probability 0.999", "min": -19, "max": 28, "total_label": "Match weight",
  "remainder_label": "ZIP rarity", "pass_text": "the pair joins", "fail_text": "the pair does not join",
  "base": [["Prior", -17.97], ["Surname", 7.65]],
  "cases": {"A–B": {"note": "Same office.", "steps": [["House number", 10.59]], "total": 26.07}},
  "default": "A–B"}
```
Each case's rows are `base` plus its `steps`. If `total` differs from the sum, the difference is added as a
final row named `remainder_label`. Set `min` and `max` to cover every running total. The bars are drawn to
scale, with a dashed line at `threshold`.

Checklist (pass or fail tests with a verdict):
```json
"checks": {"type": "checks", "title": "Worked parcels", "default": "Case one",
  "cases": {"Case one": {"note": "What this case is.",
    "rows": [["Test label", "value shown", "pass"], ["Other test", "value", "fail"], ["Context", "text", "info"]],
    "verdict": {"ok": true, "text": "Linked: why."}}}}
```
Row status is `pass`, `fail` or `info`. The status is written as a word as well as a color.

## `releases` and `evidence` (a release-evidence tab)

For a pipeline that publishes its results as a frozen dataset, a box can carry a third tab, "Release evidence",
that says what is recorded at that step, where it is stored, and shows real rows.

```json
"releases": {"v010": {"path": "~/path/to/release/v0.1.0", "label": "v0.1.0 release", "url": "https://…"}}
```
A release is a directory of CSV tables and a `manifest.json` that holds `output_checksums` (`<table>.csv` to
sha256). The builder reads a table only if its checksum matches, so a quoted row is a row of that release.

```json
"evidence": {"lede": "One or two sentences.",
  "recorded": ["What is recorded at this step."],
  "tables": [["decision_events", "What the table holds here."]],
  "examples": [
    {"release": "v010", "table": "decision_events", "where": {"decision_id": ["D0001", "D0002"]},
     "cols": ["decision_id", "outcome", "reason_code"], "limit": 4, "order_by": ["decision_id"],
     "caption": "What the rows show.", "note": "Optional line under the table."},
    {"release": "v010", "table": "manifest", "fields": ["run_id", "parameters.deed"], "caption": "…"}],
  "limits": ["What the rows cannot tell you."]}
```
An example may show a name beside an id with `"lookups": [{"col": "subject_id", "table": "identity_names",
"key": "identity_id", "take": ["name"], "as": ["subject_name"]}]`: the value is copied from the first row of that
table (of the same checksummed release) whose `key` equals the shown `col`, and the new column is placed after
it. Several `take` columns become several columns, or one if `"merge": true` (a first and last name).

`lede`, `recorded` and `tables` are required; `tables` entries are `[name, what it holds]`. In an example,
`where` maps a column to a value or a list of values, and `cols` are shown verbatim, in order. Keep to six
columns or fewer, so ids stay on one line. `table: "manifest"` shows dotted manifest keys as field and value
rows. The builder reports an example that matches no row. Say in `limits` what a row does not establish
(an absent row, a score that is not a probability, a provisional gold).

## What the builder checks

Errors (exit 1, nothing written): unknown ids, a box on a map with no entry, an edge that cannot be drawn,
a missing repo or commit, a snippet range outside the file or starting on a blank line, a notebook line not
found, a bad widget. Warnings: a commit not on a remote, text that may overflow a box, an edge that passes through another box,
a box or snippet that is never used, a view without `title` and `desc`.
