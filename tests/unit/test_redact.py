import pytest

from app.core.redact import MASK_CHAR, MIN_MASKED_LENGTH, mask_secret


def test_none_and_empty_return_empty_string() -> None:
    assert mask_secret(None) == ""
    assert mask_secret("") == ""


def test_long_value_shows_only_last_visible_chars() -> None:
    secret = "sk_live_abcdef123456"
    masked = mask_secret(secret)
    assert masked == MASK_CHAR * (len(secret) - 4) + "3456"
    assert len(masked) == len(secret)
    assert secret[:-4] not in masked


def test_custom_visible_is_respected_when_within_half_length() -> None:
    secret = "abcdefghijkl"  # 12 chars, half is 6
    assert mask_secret(secret, visible=2) == MASK_CHAR * 10 + "kl"
    assert mask_secret(secret, visible=6) == MASK_CHAR * 6 + "ghijkl"


@pytest.mark.parametrize("value", ["a", "abc", "abcdefg"])
def test_short_values_are_fully_masked(value: str) -> None:
    assert len(value) < MIN_MASKED_LENGTH
    masked = mask_secret(value)
    assert masked == MASK_CHAR * len(value)
    assert not any(ch != MASK_CHAR for ch in masked)


def test_short_value_is_fully_masked_even_with_large_visible() -> None:
    assert mask_secret("abcdefg", visible=100) == MASK_CHAR * 7


def test_value_at_min_length_is_partially_masked() -> None:
    value = "x" * (MIN_MASKED_LENGTH - 1) + "Z"
    assert len(value) == MIN_MASKED_LENGTH
    assert mask_secret(value) == MASK_CHAR * 4 + "xxxZ"


def test_visible_is_clamped_to_half_the_length() -> None:
    secret = "0123456789"  # 10 chars -> at most 5 visible
    assert mask_secret(secret, visible=8) == MASK_CHAR * 5 + "56789"
    assert mask_secret(secret, visible=1000) == MASK_CHAR * 5 + "56789"


def test_visible_zero_masks_everything() -> None:
    secret = "sk_live_abcdef123456"
    assert mask_secret(secret, visible=0) == MASK_CHAR * len(secret)


@pytest.mark.parametrize("visible", [-1, -100])
def test_negative_visible_raises_value_error(visible: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mask_secret("sk_live_abcdef123456", visible=visible)


@pytest.mark.parametrize("value", [None, ""])
def test_negative_visible_raises_even_for_empty_input(value: str | None) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mask_secret(value, visible=-1)


def test_output_never_contains_more_than_half_of_the_secret() -> None:
    for length in range(MIN_MASKED_LENGTH, 40):
        secret = "".join(chr(ord("a") + i % 26) for i in range(length))
        masked = mask_secret(secret, visible=length)
        revealed = masked.count(MASK_CHAR)
        assert revealed >= length - length // 2
        assert masked.endswith(secret[-(length // 2):])
