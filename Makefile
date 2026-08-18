# NEXUS AI root Makefile
# Python (3.14, uv + pytest) is the primary toolchain.
# apps/web and apps/tui are Node apps managed via pnpm (see their package.json).
# Recipes are POSIX-style; on Windows run them from an sh-based shell (Git Bash/WSL).

.PHONY: help install test lint api web tui clean

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*##' '{printf "%-12s %s\n", $$1, $$2}' | sort

install: ## Sync Python dependencies with uv
	uv sync

test: ## Run the Python test suite (PYTHONPATH points at the repo and src)
	PYTHONPATH="$$PWD;$$PWD\src" uv run pytest tests

lint: ## Ruff check across Python sources
	uv run ruff check src apps extensions hive memory queues security models knowledge gateways configure scripts tests

api: ## Run the FastAPI server (uvicorn; entrypoint apps.api:app)
	uv run uvicorn apps.api:app

web: ## Run the React/Vite web app (apps/web)
	pnpm --dir apps/web dev

tui: ## Run the Ink TUI (apps/tui; dev entrypoint is the 'start' script)
	pnpm --dir apps/tui start

clean: ## Remove Python cache directories
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
