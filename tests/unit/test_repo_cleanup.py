"""Guards for the repo-cleanup change: obsolete live-run artifacts removed, HITL
route module-level layout fixed, and the resolve-authorization test patching the
real Cognito verifier (not a stale Auth0 name that no longer exists).
"""

import ast
import inspect
import logging
from pathlib import Path

import pytest

from app.api.v1.routes import hitl
from app.core import security
from tests.integration import test_hitl_resolve_authorization as resolve_auth_tests

REPO_ROOT = Path(__file__).resolve().parents[2]

REMOVED_ARTIFACTS = [
    "scripts/buying_agent.py",
    "scripts/live_run.py",
    "scripts/real_transaction.py",
    "tests/e2e/test_live_spend.py",
]


@pytest.mark.parametrize("relpath", REMOVED_ARTIFACTS)
def test_obsolete_live_artifacts_are_gone(relpath: str) -> None:
    assert not (REPO_ROOT / relpath).exists(), f"{relpath} should have been removed"


def test_scripts_dir_only_keeps_migrate() -> None:
    remaining = sorted(p.name for p in (REPO_ROOT / "scripts").glob("*.py"))
    assert remaining == ["migrate.py"]


def test_no_remaining_references_to_removed_scripts() -> None:
    stems = [Path(p).stem for p in REMOVED_ARTIFACTS]
    offenders: list[str] = []
    for path in (REPO_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.relative_to(REPO_ROOT)}:{s}" for s in stems if s in text)
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.relative_to(REPO_ROOT)}:{s}" for s in stems if s in text)
    for name in ("README.md", "pyproject.toml", "Makefile"):
        path = REPO_ROOT / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            offenders.extend(f"{name}:{s}" for s in stems if s in text)
    assert offenders == []


def test_hitl_logger_is_module_scoped_logger() -> None:
    assert isinstance(hitl.logger, logging.Logger)
    assert hitl.logger.name == "app.api.v1.routes.hitl"


def test_hitl_imports_all_precede_logger_assignment() -> None:
    """Regression guard for E402: no import may follow the ``logger = ...`` line."""
    tree = ast.parse(inspect.getsource(hitl))
    body = tree.body
    logger_idx = next(
        i
        for i, node in enumerate(body)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "logger" for t in node.targets)
    )
    trailing_imports = [
        node for node in body[logger_idx + 1 :] if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert trailing_imports == []
    preceding = body[:logger_idx]
    assert preceding and all(
        isinstance(node, (ast.Import, ast.ImportFrom)) for node in preceding
    )


def test_security_exposes_cognito_verifier_not_auth0() -> None:
    assert callable(security._verify_cognito_bearer)
    assert not hasattr(security, "_verify_auth0_bearer")


def test_resolve_authorization_test_patches_real_verifier() -> None:
    """Monkeypatching a non-existent attribute would silently never take effect."""
    original = security._verify_cognito_bearer
    try:
        resolve_auth_tests._mock_bearer("cognito|someone")
        patched = security._verify_cognito_bearer
        assert patched is not original
        ctx = patched("any-token")
        assert isinstance(ctx, security.UserAuthContext)
        assert ctx.sub == "cognito|someone"
    finally:
        security._verify_cognito_bearer = original
    assert security._verify_cognito_bearer is original


def test_resolve_authorization_test_source_uses_cognito_names_only() -> None:
    source = inspect.getsource(resolve_auth_tests)
    assert "auth0" not in source.lower()
    assert "_verify_cognito_bearer" in source
