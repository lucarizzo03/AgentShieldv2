# Agent instructions for AgentShieldv2

## Project basics

- Python 3.11+, FastAPI, SQLModel, Redis. Deps: `uv pip install --python .venv/bin/python -e ".[dev]"`.
- Lint: `.venv/bin/python -m ruff check app tests`
- Tests: `redis-server --daemonize yes --port 6379 && APP_ENV=dev .venv/bin/python -m pytest -q --ignore=tests/e2e --ignore=tests/unit/test_engine.py`
  (`tests/e2e` and the Claude-backed tests in `tests/unit/test_engine.py` are excluded because they need a
  live server / `ANTHROPIC_API_KEY`; drop the `--ignore` flags to run them once those are available.)
- Dashboard: `cd dashboard && npm install && npm run build`

## Testing is handed off to the cloud

Do not write the test suite for a new feature yourself. When a feature (or bug fix) is
implemented locally and is ready for testing, hand it off to the cloud testing agent by
following the `test-handoff` skill in `.agents/skills/test-handoff/SKILL.md`:

1. Make sure the code imports and `ruff check app tests` is clean.
2. Commit on a feature branch (never `main`) with a message containing `[test-handoff]`
   followed by a short description of the feature and what should be tested.
3. Push the branch.

A cloud session then writes the tests, fixes any failures in the feature, iterates until
green, and opens/updates the PR. Do not open the PR yourself.
