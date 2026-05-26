import os

import pytest

# Override DB/Redis before any app module is imported so the lru_cache picks up
# the test values, not the Railway URLs from .env.
os.environ["POSTGRES_DSN"] = "sqlite:///./test_isolated.db"
os.environ["REDIS_DSN"] = "redis://localhost:6379/1"

# If get_settings() was already cached (e.g. by a top-level import in a helper),
# bust the cache so the test overrides take effect.
try:
    from app.core.config import get_settings
    get_settings.cache_clear()
except Exception:
    pass


# Integration tests patch AnthropicSemanticClient methods at the class level
# without cleanup. This autouse fixture restores the originals after every test
# so class-level mocks don't leak into subsequent tests (especially engine tests
# that need the real Claude API).
from app.services.slm.client import AnthropicSemanticClient as _SLMClient

_orig_semantic_alignment = _SLMClient.semantic_alignment
_orig_goal_scope_check = _SLMClient.goal_scope_check


@pytest.fixture(autouse=True)
def _restore_slm_client():
    yield
    _SLMClient.semantic_alignment = _orig_semantic_alignment
    _SLMClient.goal_scope_check = _orig_goal_scope_check
