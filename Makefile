.DEFAULT_GOAL := help

# Airflow is a peer dependency installed into the venv out-of-band (see setup),
# not tracked in the lockfile. Stop `uv run`'s implicit sync from pruning it —
# explicit `uv sync` / `uv lock` are unaffected by this flag.
export UV_NO_SYNC := 1

FRONTEND := frontend

##@ General

.PHONY: help
help:  ## Print this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Setup

.PHONY: setup
setup:  ## Create the uv venv (dev group + airflow) and install pre-commit hooks
	bash scripts/setup.sh

.PHONY: setup-refresh-lock
setup-refresh-lock:  ## Bump uv.lock to the latest versions allowed by pyproject ranges, then setup
	UPDATE_LOCK=true bash scripts/setup.sh

.PHONY: sync
sync:  ## uv sync from the lockfile (frozen), dev group
	uv sync --frozen --group dev

.PHONY: sync-lock
sync-lock:  ## Re-resolve the lockfile then sync
	uv lock && uv sync --group dev

##@ Quality

.PHONY: pre-commit
pre-commit:  ## Run all pre-commit hooks (ARGS=<hook-id> to target one)
	bash scripts/run_pre_commit.sh $(ARGS)

.PHONY: test
test:  ## Run pytest (ARGS forwarded, e.g. ARGS="-k core -vv")
	uv run pytest $(ARGS)

.PHONY: ty
ty:  ## Type-check the package
	uv run ty check src/ $(ARGS)

.PHONY: smoke
smoke:  ## Integration smoke: run the DB loader against a throwaway Airflow metadb
	uv run python scripts/smoke_loader.py

.PHONY: lint
lint:  ## ruff check + format check (no fixes)
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

##@ Frontend

.PHONY: frontend-install
frontend-install:  ## Install frontend dependencies (npm)
	npm --prefix $(FRONTEND) install

.PHONY: frontend-build
frontend-build:  ## Build the React UI into src/schedule_visualizer/static/
	npm --prefix $(FRONTEND) run build

.PHONY: frontend-dev
frontend-dev:  ## Vite dev server (proxies /api to the demo backend; run `make demo-api`)
	npm --prefix $(FRONTEND) run dev

.PHONY: frontend-refresh-lock
frontend-refresh-lock:  ## Bump frontend deps to the latest allowed by package.json ranges
	npm --prefix $(FRONTEND) update

##@ Release

.PHONY: build
build: frontend-build  ## Build the wheel + sdist into dist/ (frontend bundled first)
	rm -rf dist && uv build

.PHONY: bump
bump:  ## Bump version (pyproject + frontend package.json) via commitizen. ARGS=patch|minor|major
	uv run cz bump $(ARGS)

.PHONY: bump-dry
bump-dry:  ## Preview the next version bump without writing anything
	uv run cz bump --dry-run $(ARGS)

##@ Demo

.PHONY: demo
demo:  ## Build the UI and serve seeded data at http://127.0.0.1:8888
	@test -d $(FRONTEND)/node_modules || npm --prefix $(FRONTEND) install
	npm --prefix $(FRONTEND) run build
	uv run python scripts/demo.py

.PHONY: demo-api
demo-api:  ## Serve seeded data only (no UI build; pair with `make frontend-dev`)
	uv run python scripts/demo.py

##@ Housekeeping

.PHONY: clean
clean:  ## Remove caches, build and frontend artifacts
	rm -rf .ruff_cache .ty_cache .pytest_cache dist build src/schedule_visualizer/static
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
