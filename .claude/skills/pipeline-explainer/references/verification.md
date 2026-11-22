# Verification

Three layers. Do all three before publishing, and once after any edit to the template.

## 1. Static (the builder does this)

`build.py` fails on errors and prints warnings. It catches the mistakes that are easy to make and hard to
see: a snippet whose line range drifted, a box with no details, an arrow between boxes that do not line up,
a commit that is not pushed. Treat every warning as a question to answer, not noise.

## 2. Content (you do this)

- Re-run the example and confirm every number in `nums`. Check each `measured` figure against its source
  (the project's evaluation output or README), including the sample size and interval.
- Read each `what` bullet against the code it summarizes. A bullet that the code does not support must go.
- Check that `open` names the real limits: what is not measured, what is provisional, what is exploratory.
- Check the privacy line: nothing the user has not released, no names beyond what the example needs.
- Read the page as the intended reader. Is the weakest stage visible on the map, not just in a panel?

## 3. Browser (Browser pane)

1. Serve the preview: `cd <dir> && python3 -m http.server 8770 &`, then open
   `http://localhost:8770/preview.html?v=1`. Add a new `?v=N` on each rebuild, because navigating to the
   same URL with only a different hash does not reload.
2. Run `scripts/browser_checks.js` with `javascript_tool` (action `javascript_exec`). It returns
   `{problems, info}`. `problems` must be empty. It checks that:
   - every map box has details and every detail has a map box;
   - every SVG marker is defined inside its own SVG;
   - every box renders its Annotation tab, and its widget if it has one;
   - every Code tab renders one row per source line, the rendered text equals the source, and no snippet
     scrolls sideways;
   - every view tab opens, and the page itself never scrolls sideways;
   - highlight.js loaded.
3. Check the console: `read_console_messages` with `onlyErrors`. It should be empty.
4. Look once at each view in a screenshot, desktop width. Check arrow routes, label positions, text inside
   boxes, and the first panel.
5. Phone width: `resize_window` with preset `mobile`, reload with a new `?v=N`, rerun the checks, then reset
   with preset `desktop`. The page must not scroll sideways, and code should scroll only inside its box,
   if at all.
6. Stop the server: `pkill -f "http.server 8770"`.

If the pane is hidden, screenshots time out and `innerWidth` reads 0. The checks report that as a problem.
Show the pane and run them again.

## Typical failures and fixes

| Symptom | Cause | Fix |
|---|---|---|
| Arrow missing on the second view | marker defined in another SVG | builder already gives each view its own; re-check custom SVG |
| Title runs past its box | too long for the box width | shorten, or widen the box in a manual view |
| Code scrolls sideways | long line in a narrow panel | shorten the excerpt, or accept wrapping; the Code tab already widens the panel |
| Letters stacked vertically in a widget row | a grid column collapsed | give the columns `minmax(0, 1fr)` in the template |
| Snippet link 404s | commit not pushed | push, or pin a pushed commit |
| Old page after a rebuild | same URL, new hash only | add a new `?v=N` |
