.DEFAULT_GOAL := help
.PHONY: help setup test test-live eval lint fmt check sidecar sidecar-stop

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

setup:  ## Install dependencies
	uv sync

test:  ## Fast tests (no Neo4j or sidecar needed)
	uv run pytest -k "not live"

test-live:  ## Live tests (need Neo4j and the Geosupport sidecar; skip if unreachable)
	uv run pytest -k live -rs

eval:  ## Q1 tool-level evals (need Neo4j and the sidecar; skip if unreachable)
	uv run pytest tests/test_eval_q01.py -rs

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
