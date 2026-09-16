"""Helpers for safely displaying secrets (API keys, HMAC secrets) in logs and UIs."""

MASK_CHAR = "*"
MIN_MASKED_LENGTH = 8


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Return ``value`` with all but the last ``visible`` characters masked.

    Values shorter than ``MIN_MASKED_LENGTH`` are fully masked so that short
    secrets never leak most of their content. ``None`` and empty strings
    return an empty string.
    """
    if visible < 0:
        raise ValueError("visible must be non-negative")
    if not value:
        return ""
    if len(value) < MIN_MASKED_LENGTH or visible == 0:
        return MASK_CHAR * len(value)
    visible = min(visible, len(value) // 2)
    return MASK_CHAR * (len(value) - visible) + value[-visible:]


def is_partially_masked(value: str | None) -> bool:
    """Return True when ``value`` contains mask characters but is not fully masked."""
    if not value:
        return False
    return MASK_CHAR in value and not all(ch == MASK_CHAR for ch in value)
