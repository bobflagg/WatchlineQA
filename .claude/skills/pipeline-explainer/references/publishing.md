# Publishing

The Artifact tool's own instructions are authoritative and can change. This file records what the
explainer needs from them and the order that worked.

1. Build: `python3 scripts/build.py spec.json out.html --local preview.html`. `out.html` is a fragment (a
   `<title>`, a `<style>`, markup and scripts, no `<html>` or `<body>`), which is what the Artifact tool
   expects. Do not call `quickstart` for this: it is a plain page, and the design is already settled.
2. Verify with `references/verification.md`.
3. Publish `out.html` with the Artifact tool. On the first publish pass:
   - `icon`: one short generic word such as `diagram`.
   - `description`: one sentence for the gallery card.
   Omit `icon` on updates. Update by publishing the same file path again. A different path creates a new
   artifact.
4. Tell the user the URL, that it is private until they share it from the page's Share menu, and which
   figures on the page are provisional. You cannot change sharing.

## What the viewer allows

- Scripts only from `cdnjs.cloudflare.com`, `cdn.jsdelivr.net/npm/`, `unpkg.com`, `cdn.tailwindcss.com` and
  `code.jquery.com`. Stylesheets only from Google Fonts. The template uses Google Fonts and highlight.js
  11.9.0 from cdnjs, and inlines everything else.
- No `alert`, `confirm` or `prompt`, no downloads started by the page, no printing.
- `localStorage` may be empty or blocked; the template does not use it.
- Copy buttons need `navigator.clipboard.writeText` called inside the click handler, so they fall back to
  selecting the text if the browser refuses.
- Only a plain `#token` reaches `location.hash`, which is why deep links are `#node` and `#node-code`.

## Theming

The template defines every color as a token on `:root`, redefines them under
`prefers-color-scheme: dark` guarded by `:root:not([data-theme="light"])` and again under
`:root[data-theme="dark"]`, and sets an explicit `body` background. Keep that shape if you edit it. A
color that only exists inside a dark block shows as unreadable text in light mode.

## Sharing notes

A link from a public page to a private artifact will not open for other people. If the explainer is meant
to be linked from a README or an email, the user must set sharing to "anyone with the link" first.
Snippet permalinks point at GitHub, so they work only if the repo is public or the reader has access.
