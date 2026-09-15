---
name: test-handoff
description: Hand a locally implemented feature or fix off to the cloud testing agent, which writes the tests, fixes failures, and opens the PR. Use whenever a feature is done being built and it is time for testing.
---

# Hand off a finished feature for cloud testing

AgentShieldv2 has an automation that watches the repo for the marker `[test-handoff]`.
When it sees it, a cloud Devin session checks out the branch, writes pytest tests for the
diff, runs ruff + pytest (with Redis), fixes real bugs in the feature code, iterates until
green, and opens or updates the PR with a summary comment.

Your job as the local agent is only to build the feature and send the signal.

## When to use

- You have finished implementing a feature, refactor, or bug fix and would normally start
  writing tests.
- The user says the feature is done, "test this", "hand off", or similar.

Do NOT use it for work-in-progress pushes; every marker push starts a cloud session.

## Steps

1. Sanity-check locally (fast, no full suite needed):
   ```bash
   .venv/bin/python -m ruff check app tests
   .venv/bin/python -c "import app.main"
   ```
   Fix anything that fails before handing off.

2. Be on a feature branch, never `main`/`master`:
   ```bash
   git checkout -b feat/<short-slug>   # if not already on one
   ```

3. Commit with the marker and a testing brief. Put the marker in the **last** commit of
   the push; the automation reads only the head commit message. Format:
   ```
   <what the feature does> [test-handoff] — test <modules/endpoints>: <behaviors, edge cases, expected statuses/policy outcomes>
   ```
   Example:
   ```bash
   git commit -am "Add per-merchant daily cap to Check A [test-handoff] — test app/policy/check_a.py and POST /v1/spend: cap enforced per merchant per UTC day, SUSPICIOUS (202) when exceeded, resets at midnight, unaffected merchants still SAFE"
   ```
   The text after the marker is the cloud agent's only hint about intent, so name the
   files touched, the behaviors to cover, and the expected HTTP status / SAFE-SUSPICIOUS-
   MALICIOUS verdicts.

4. Push the branch:
   ```bash
   git push -u origin HEAD
   ```

5. Stop. Do not open a PR and do not write the test suite yourself. Tell the user the
   handoff was sent; the cloud session appears at https://app.devin.ai within ~30 seconds
   and posts its results on the PR when done.

## Alternative signal

Opening (or retitling) a PR whose title contains `[test-handoff]` also triggers the
cloud tester. Prefer the commit-message route from a terminal since it needs no PR.

## Follow-up work

If the cloud agent's PR comment reports an unresolved failure, fix it locally and push
another `[test-handoff]` commit to the same branch to re-run.
