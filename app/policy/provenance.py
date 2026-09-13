"""Provenance stamped on every audit row.

A verdict is only explainable if the inputs that produced it are recoverable.
Thresholds move, prompts get edited and the model is pinned by name, so a row
holding only the check contexts cannot answer "would we decide this the same
way today, and if not, what changed?".
"""

from app.core.config import get_settings
from app.services.slm.client import SCOPE_PROMPT_VERSION, SEMANTIC_PROMPT_VERSION

ENGINE_VERSION = "0.1.0"


def engine_provenance() -> dict:
    settings = get_settings()
    return {
        "engine_version": ENGINE_VERSION,
        "model_name": settings.anthropic_model_name,
        "prompt_versions": {
            "semantic_alignment": SEMANTIC_PROMPT_VERSION,
            "goal_scope": SCOPE_PROMPT_VERSION,
        },
        "thresholds": {
            "semantic_aligned_min_score": settings.semantic_aligned_min_score,
            "semantic_weak_suspicious_min_score": settings.semantic_weak_suspicious_min_score,
            "goal_drift_min_confidence": settings.goal_drift_min_confidence,
            "loop_threshold": settings.loop_threshold,
            "loop_window_seconds": settings.loop_window_seconds,
            "slm_deadline_seconds": settings.slm_deadline_seconds,
        },
    }
