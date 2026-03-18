.PHONY: lint format type test test_integration test_watch help

.DEFAULT_GOAL := help

TEST_FILE ?= tests/unit_tests
INTEGRATION_FILES ?= tests/integration_tests

test: ## Run unit tests
	uv run pytest --disable-socket --allow-unix-socket $(TEST_FILE)

test_integration: ## Run integration tests
	uv run pytest $(INTEGRATION_FILES)

test_watch: ## Run tests in watch mode
	uv run ptw . -- $(TEST_FILE)

lint format: PYTHON_FILES=superagents/ tests/
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=. --name-only --diff-filter=d main | grep -E '\.py$$')

lint: ## Run linters and type checker
lint lint_diff:
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff format $(PYTHON_FILES) --diff
	@if [ "$(LINT)" != "minimal" ]; then \
		if [ "$(PYTHON_FILES)" != "" ]; then \
			uv run --group test ruff check $(PYTHON_FILES) --diff; \
		fi; \
	fi
	$(MAKE) type PYTHON_FILES="$(PYTHON_FILES)"

type: ## Run type checker
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ty check $(PYTHON_FILES)

format: ## Run code formatters
format format_diff:
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff format $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run --group test ruff check --fix $(PYTHON_FILES)

help: ## Show this help message
	@echo "Usage: make [target] [TEST_FILE=path/to/tests/]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
