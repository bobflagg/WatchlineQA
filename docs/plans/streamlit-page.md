# Streamlit page (bare bones)

Branch: `streamlit-page`. Goal: render the structured answer contract (`watchline/agent/answer.py`) in a Streamlit chat page, to test
the contract against real data. Skills: `developing-with-streamlit`, `watchline-ui`.

## Files
- `watchline/ui/render.py`: `render_answer(answer)` takes an `Answer` and calls Streamlit. No agent or graph imports.
- `watchline/ui/app.py`: chat page. Uses `connect()`, `build_agent()` and `ask()` from `watchline/agent/chat.py`. Clients and agent are
  cached with `st.cache_resource`; the thread id lives in `st.session_state`.
- `watchline/ui/fixtures.py`: one hand-built `Answer` per kind (profile, clarification, not_found, refusal, error), plus a
  caveat-heavy one and one with no facts.
- `.streamlit/config.toml`: theme from `.claude/skills/watchline-ui/references/tokens.md`.
- `Makefile`: `make ui` runs `streamlit run watchline/ui/app.py`.
- Tests: a smoke test per fixture with `streamlit.testing.v1.AppTest`.

## Rendering order (per `answer-rendering.md`)
1. Summary.
2. Facts as a list: statement plus a quiet tag per evidence section. Unresolved references show "unverified reference".
3. One visible caveat line under the facts whenever the answer has caveats.
4. Collapsed expander "Evidence: what this answer rests on": evidence data per fact, all caveats, sources.
5. A visible warning if `Turn.unverified` has numbers; a note if `Turn.structured` is None.

## Left out for now
- Navy/gold banner, logo, sidebar sample questions, chips, side panel.
- Per-kind renderers (all kinds use the generic path, to show where the contract falls short).
- Lead / record / finding pills: the contract has no lead flag on caveats yet. Add it with the first tool that returns leads.
- Streaming.

## Checks
1. `make check` and the smoke tests.
2. Look at the page in a browser: fixtures first, then live data (a caveat-heavy answer, an empty answer).
3. Update `docs/status.md`.
