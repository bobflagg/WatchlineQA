.DEFAULT_GOAL := help
.PHONY: help setup test test-live eval eval-agent chat ui notebook notebook-check lint fmt check sidecar sidecar-stop

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup:  ## Install dependencies
	uv sync

test:  ## Fast tests (no Neo4j or sidecar needed)
	uv run pytest -k "not live" -m "not llm"

test-live:  ## Live tests (need Neo4j and the Geosupport sidecar; skip if unreachable)
	uv run pytest -k live -m "not llm" -rs

eval:  ## Q1, Q2 and Q3 tool-level evals (need Neo4j and the sidecar; skip if unreachable)
	uv run pytest tests/test_eval_q01.py tests/test_eval_q02.py tests/test_eval_q03.py -rs

eval-agent:  ## Agent-level evals on the real model (need Neo4j, the sidecar and EVAL_ANTHROPIC_API_KEY; costs money, stops at EVAL_MAX_USD, default $0.25). EVAL_JUDGE=1 adds the LLM judge
	uv run pytest -m llm -rs -v

chat:  ## Terminal chat with the agent (needs Neo4j, the sidecar and AGENT_ANTHROPIC_API_KEY)
	uv run python -m watchline.agent.chat

ui:  ## Streamlit page (needs Neo4j, the sidecar and AGENT_ANTHROPIC_API_KEY; add ?fixtures=1 to the URL to preview without them)
	uv run streamlit run watchline/ui/app.py

notebook:  ## Re-execute the notebooks in place (need Neo4j, the sidecar and AGENT_ANTHROPIC_API_KEY; the agent notebook calls the model); commit the refreshed outputs
	uv run jupyter nbconvert --to notebook --execute --inplace docs/notebooks/*.ipynb

notebook-check:  ## Execute the notebooks into build/ to catch drift (same needs as `notebook`); the committed copies are untouched
	uv run jupyter nbconvert --to notebook --execute --output-dir build/notebook-check docs/notebooks/*.ipynb

lint:  ## Lint with ruff
	uv run ruff check .

fmt:  ## Format with ruff
	uv run ruff format .

check: lint test  ## Ready-to-commit gate: lint plus fast tests

sidecar:  ## Build and start the Geosupport sidecar (Docker, linux/amd64)
	docker build --platform=linux/amd64 -t watchline-geosupport geosupport/
	docker run -d --platform=linux/amd64 -p 8080:8080 --name geosupport watchline-geosupport

sidecar-stop:  ## Stop and remove the Geosupport sidecar
	docker rm -f geosupport
