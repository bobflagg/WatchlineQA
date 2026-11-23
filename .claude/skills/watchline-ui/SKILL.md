---
name: watchline-ui
description: The Watchline visual style and layout conventions for Streamlit UI work. Use when building or changing any Streamlit page, component or theme for WatchlineQA, including how structured answers, leads, caveats and evidence are displayed. Load alongside developing-with-streamlit.
---

# Watchline UI

Style and conventions for the WatchlineQA Streamlit app. Extracted from an earlier Watchline UI; the style is
kept, the old code is not. Streamlit API details come from `developing-with-streamlit`, not from here.

## Principles

1. **Navy and gold, light content area.** Navy sidebar and brand banner, gold accent, white main panel.
2. **Caveats are never hidden.** A lead is always labelled as a lead where it appears. Details sit in the
   Evidence expander, but the label and a one-line caveat stay visible. See `references/answer-rendering.md`.
3. **Render the contract, don't parse text.** Pages render the structured answer (summary, facts with
   evidence, caveats, sources, `kind`). No UI code extracts meaning from markdown.
4. **UI code stays thin.** Rendering lives in `watchline/ui/`, separate from agent and graph code. One
   renderer per answer `kind`, plus a generic fallback.
5. **Plain and sober.** This is accountability tooling for journalists and tenants. No decorative emoji in
   answers, no alarm colors for anything that is only a lead.

## Files

- `references/tokens.md`: palette, status colors, type, the theme to copy into `.streamlit/config.toml`.
- `references/layout-patterns.md`: brand banner, sidebar, chat, side panel, chips, tables.
- `references/answer-rendering.md`: how each part of a structured answer is shown. Read before writing a renderer.
- `assets/logo.png`: the Watchline NYC logo (top of the sidebar).
- `assets/config.toml`: the earlier app's Streamlit theme, for reference. `tokens.md` has the one to use.

## Process

1. Read `tokens.md` and `layout-patterns.md` before the first UI change in a session.
2. Build or change a renderer against the answer contract, with fixture data first, then live data.
3. Look at the page in a browser before calling it done. Check a lead, a caveat-heavy answer and an empty answer.
4. If you make a new style decision, add it to the matching reference file, not just the code.
