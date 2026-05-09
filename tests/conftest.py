import os

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
