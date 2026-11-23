# Tokens

Source: the earlier Watchline UI's report styling and Streamlit theme.

## Palette

| Token | Hex | Use |
|---|---|---|
| navy | `#0a1629` | Sidebar, brand banner |
| navy-2 | `#12243f` | Chips, secondary dark surfaces |
| gold | `#d4a017` | Accent: banner edge, chip numbers, tagline |
| ink | `#1b2430` | Body text |
| muted | `#5c6b80` | Secondary text, captions |
| faint | `#8290a3` | Tertiary labels |
| line | `#e3e7ee` | Borders, dividers |
| bg | `#eef1f5` | Page and panel backgrounds |
| card | `#ffffff` | Cards, main area |

## Status colors (soft background, darker text)

| Meaning | Text | Background |
|---|---|---|
| Danger | `#b0261c` | `#fbeae7` |
| Warning | `#8a5a00` | `#fdf3df` |
| OK | `#256a4c` | `#e7f4ee` |
| Info | `#1c4e86` | `#eef3fb` |

For Watchline: **lead** uses Warning. **Recorded finding** (for example a harassment finding) uses Danger.
**Record-only facts** are neutral. Never use OK green to mean "cleared": absence of a link is not evidence.

## Type

- Sans (UI): `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`
- Serif (report titles only): `Georgia, "Iowan Old Style", "Times New Roman", serif`
- Mono (ids, BBLs, code): `ui-monospace, "SF Mono", Menlo, Consolas, monospace`
- Small caps-style labels: 0.66rem, uppercase, letter-spacing 0.14 to 0.26em, muted or gold.

## Streamlit theme (`.streamlit/config.toml`)

```toml
[client]
showErrorDetails = "none"

[theme]
base = "light"
primaryColor = "#d4a017"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#eef1f5"
textColor = "#1b2430"
showWidgetBorder = true

[theme.sidebar]
backgroundColor = "#0a1629"
secondaryBackgroundColor = "#12243f"
primaryColor = "#d4a017"
borderColor = "#22344b"
```

Note: the earlier app used pink (`#F63366`) as primary and white sidebar accents. This draft moves the primary
to gold to match the brand banner. Confirm in a browser and adjust if contrast is poor.
