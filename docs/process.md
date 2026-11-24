# Process

A light, single-developer version of the AI-native SDLC. The goal is to move fast with Claude
while the developer still understands the key components and how they work.

## The loop for each slice

A slice is one small, end-to-end piece of behavior (for example: "type an address, get a building profile").

1. **Intent.** The slice starts from a competency question in `specs/questions/`. If the question is
   vague, tighten it first: expected answer shape, caveats, what counts as done.
2. **Plan.** Claude proposes a short plan (plan mode). The developer skims it and approves before any
   code is written. Non-trivial plans are saved as `docs/plans/<slice>.md`.
3. **Build** on a short-lived branch, in small commits.
4. **Check.** Unit tests for tools; eval cases drawn from the question. Run `make check` before
   calling anything done. Evals rerun whenever tools, skills or prompts change.
5. **Review.** A fresh-context review pass (a subagent that did not build it) reads the diff against the
   question and the ontology rules in CLAUDE.md. The developer reads the explainer, not every line.
6. **Understand.** Update the explainer for any component whose behavior changed (see below).
7. **Merge**, then push so code pins in the explainer resolve.

## Understanding step: explainers for components, notebooks for tools

Understanding is a bottleneck: the developer needs a working mental model of the key components, not
line-by-line knowledge. We keep a small set of explainers for that, and a notebook for each simple tool.

- **Notebook per tool** (`docs/notebooks/<tool>.ipynb`): for a thin tool, a notebook that calls it on real
  addresses and shows what the model sees, including the failure statuses and the caveats. Committed
  executed, with the run date and data snapshot in the first cell. `make notebook` refreshes it in place;
  `make notebook-check` executes it without touching the committed copy, to catch drift. Both need Neo4j and
  the sidecar, and the agent notebook (`watchline-agent-chat.ipynb`, which drives the chat's own functions) also
  calls the model, so it needs `AGENT_ANTHROPIC_API_KEY` and its wording changes on each run. Credentials come from `.env` through code and are never printed.
- **Explainer per component** (below): for anything with real stages or flow.

- One explainer per key component (agent flow, graph tools, address resolution, ontology and its traps),
  not one per change. Start with the first after the first working slice.
- Built with the `pipeline-explainer` skill (`.claude/skills/pipeline-explainer/`): a clickable map, with
  Annotation and Code tabs per box and snippets pinned verbatim to a pushed commit. The Evidence tab
  shows real graph query results, labelled with the date they were run.
- Spec committed in `docs/understanding/<name>/spec.json`; rendered page published as an artifact.
- Refresh at the end of any slice that changes the component, including the commit pin.
- No quizzes or micro-worlds for now.

## Guardrails (enforced by hooks where possible)

- Never read or edit `.env`. Never touch `ignore-this-directory/`.
- Neo4j access is read-only.
- Run `make check` before each commit.

## Agent architecture decisions (so far)

- Runtime Neo4j access uses the Python driver through curated, parameterized, read-only tools with
  row limits and timeouts. Each tool returns evidence plus the caveats that apply.
- The Neo4j MCP server is for development and exploration, and possibly a guarded fallback later.
- Ontology rules live in one place, `watchline/agent/prompts/ontology_rules.md`, and feed both CLAUDE.md (dev time, by `@` import) and
  the agent's system prompt (run time).
- Model-calling evals are separate from `make check` (`make eval-agent`): they cost money and vary run to run.
- Web search comes after the graph side is solid. Web results are context, never identity evidence.

## Deliberately skipped

CI/CD pipelines, parallel sessions, approval gates, metrics dashboards. Revisit if the project grows.
