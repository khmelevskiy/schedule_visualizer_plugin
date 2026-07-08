# Contributing

Thanks for helping out. This is a small, layered codebase — keep changes focused
and the layers honest.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node.

```bash
make setup   # uv venv + Airflow (peer dep) + pre-commit hooks
make demo    # build the UI and serve seeded data at http://127.0.0.1:8888
```

## Before you push

All three must be green:

```bash
make test         # unit + doctests (no Airflow DB needed)
make smoke        # loader against a throwaway Airflow metadb
make pre-commit   # ruff, ruff-format, ty, gitleaks, yamllint
```

Run `make smoke` after bumping Airflow — the metadata-DB model API is the most
likely thing to drift between minors, and it's the one path unit tests can't cover.

## Where things go (ports & adapters)

- **Pure logic** (`core.py`, `suggest.py`, `cache.py`, `config.py`) — no Airflow,
  no I/O. New aggregation or placement logic lives here and is unit-tested directly.
- **Airflow-coupled I/O** (`airflow_io/`) — timetable expansion and metadata-DB
  reads. Keep the Airflow surface confined here; a scheduler change should touch
  only this folder.
- **HTTP** (`web/`) and **frontend/** — serialization, FastAPI app, React UI.

If a change spans layers, that's usually a sign the boundary is in the wrong place —
say so in the PR.

## Conventions

- Python 3.14, modern syntax (PEP 695 `type`/generics, no `from __future__`).
  Docstrings are numpy-style; comments explain *why*, never restate code.
- Times are UTC end to end (see the note in `README.md`).
- Code, comments and commits in English.
- **Conventional Commits**: the `commit-msg` hook checks your local commits, and
  since PRs are squash-merged the **PR title** becomes the commit — so it must be
  a Conventional Commit too. `make bump` sets the next version across
  `pyproject.toml` and the frontend.

## Pull requests

`main` is protected — changes land via PR, squash-merged (the PR title becomes the
commit, its branch auto-deleted). Keep them small and reviewable; describe the risk
for anything touching dependencies, the plugin entry point, or the metadata-DB queries.
