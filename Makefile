# NEXUS AI — Cross-platform Makefile (works on Windows/macOS/Linux)
# Usage:
#   make setup       Install dependencies
#   make api         Start API server
#   make gui         Start GUI frontend
#   make run         Start API + GUI (default)
#   make network     Start in network mode (all devices)
#   make terminal    Start terminal shell
#   make test        Run Python tests
#   make tsc         TypeScript type-check
#   make lint        TypeScript lint
#   make build       Build GUI for production
#   make clean       Clean generated files

SHELL := /bin/bash
OS := $(shell uname -s 2>/dev/null || echo Windows)
ROOT := $(shell pwd)
VENV_PY := $(ROOT)/.venv/bin/python
NPM_CMD := npm
PYTEST := $(VENV_PY) -m pytest

ifeq ($(OS),Windows)
VENV_PY := $(ROOT)/.venv/Scripts/python.exe
NPM_CMD := npm.cmd
PYTEST := $(VENV_PY) -m pytest
endif

.PHONY: setup api gui run network terminal test tsc lint build clean help

help:
	@echo "NEXUS AI — Cross-platform Makefile"
	@echo ""
	@echo "  make setup       Install dependencies"
	@echo "  make api         Start API server (port 8000)"
	@echo "  make gui         Start GUI frontend (port 5173)"
	@echo "  make run         Start API + GUI"
	@echo "  make network     Start in network mode (any device)"
	@echo "  make terminal    Start terminal shell"
	@echo "  make test        Run Python tests"
	@echo "  make tsc         TypeScript type-check"
	@echo "  make build       Build GUI for production"
	@echo "  make clean       Clean generated files"
	@echo ""

setup:
	python -m pip install -e ".[voice,dev]"
	cd gui && $(NPM_CMD) install
	cd cli && $(NPM_CMD) install

api:
	$(VENV_PY) -m uvicorn gui.api:app --host 127.0.0.1 --port 8000 --reload

gui:
	cd gui && $(NPM_CMD) run dev

run:
	$(VENV_PY) -m uvicorn gui.api:app --host 127.0.0.1 --port 8000 & \
	cd gui && $(NPM_CMD) run dev

network:
	NEXUS_DASHBOARD_LOCAL_ONLY=false $(VENV_PY) -m uvicorn gui.api:app --host 0.0.0.0 --port 8000 & \
	cd gui && $(NPM_CMD) run dev -- --host 0.0.0.0

terminal:
	$(VENV_PY) -c "from shell import NexusShell; NexusShell().start()"

test:
	$(PYTEST) tests/ -q

tsc:
	cd cli && npx tsc --noEmit
	cd gui && npx tsc --noEmit

lint:
	cd gui && npx eslint .

build:
	cd gui && npx tsc -b && npx vite build

clean:
	rm -rf workspace/__pycache__ workspace/*.json workspace/work_events/*.jsonl logs/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
