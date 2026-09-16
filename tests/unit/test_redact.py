import pytest

from app.core.redact import (
    MASK_CHAR,
    MIN_MASKED_LENGTH,
    is_masked,
    mask_all,
    mask_secret,
)


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


@pytest.mark.parametrize("value", [MASK_CHAR, MASK_CHAR * 7, MASK_CHAR * 64])
def test_is_masked_true_for_only_mask_chars(value: str) -> None:
    assert is_masked(value) is True


@pytest.mark.parametrize("value", [None, ""])
def test_is_masked_false_for_none_and_empty(value: str | None) -> None:
    assert is_masked(value) is False


@pytest.mark.parametrize(
    "value",
    [
        "sk_live_abcdef123456",
        MASK_CHAR * 16 + "3456",
        "a" + MASK_CHAR * 10,
        MASK_CHAR * 5 + "x" + MASK_CHAR * 5,
        " " + MASK_CHAR * 8,
        MASK_CHAR * 8 + "\n",
        "x",
    ],
)
def test_is_masked_false_when_any_non_mask_char_present(value: str) -> None:
    assert is_masked(value) is False


def test_is_masked_does_not_treat_other_placeholder_chars_as_mask() -> None:
    for ch in ("\u2022", "#", "x", "-"):
        assert ch != MASK_CHAR
        assert is_masked(ch * 12) is False


@pytest.mark.parametrize("value", ["a", "abc", "abcdefg"])
def test_is_masked_recognises_fully_masked_short_secrets(value: str) -> None:
    assert is_masked(mask_secret(value)) is True


def test_is_masked_recognises_visible_zero_output() -> None:
    assert is_masked(mask_secret("sk_live_abcdef123456", visible=0)) is True


def test_is_masked_false_for_partially_masked_output() -> None:
    secret = "sk_live_abcdef123456"
    assert is_masked(mask_secret(secret)) is False
    assert is_masked(mask_secret(secret, visible=1)) is False
    assert is_masked(secret) is False


def test_is_masked_is_idempotent_with_mask_secret() -> None:
    masked = mask_secret("sk_live_abcdef123456", visible=0)
    assert is_masked(masked) is True
    assert is_masked(mask_secret(masked)) is True


def test_mask_all_empty_list_returns_empty_list() -> None:
    assert mask_all([]) == []


def test_mask_all_handles_mixed_none_empty_short_and_long_values() -> None:
    values: list[str | None] = [None, "", "abc", "sk_live_abcdef123456"]
    assert mask_all(values) == [
        "",
        "",
        MASK_CHAR * 3,
        MASK_CHAR * 16 + "3456",
    ]


def test_mask_all_preserves_order_and_length() -> None:
    values: list[str | None] = ["sk_live_abcdef123456", None, "abcdefghijkl", ""]
    masked = mask_all(values)
    assert len(masked) == len(values)
    assert masked == [mask_secret(v) for v in values]


def test_mask_all_passes_visible_through_to_mask_secret() -> None:
    values: list[str | None] = ["abcdefghijkl", "0123456789", "abc"]
    assert mask_all(values, visible=2) == [
        MASK_CHAR * 10 + "kl",
        MASK_CHAR * 8 + "89",
        MASK_CHAR * 3,
    ]
    assert mask_all(values, visible=1000) == [mask_secret(v, visible=1000) for v in values]


def test_mask_all_visible_zero_masks_everything() -> None:
    values: list[str | None] = ["sk_live_abcdef123456", "abc", None]
    masked = mask_all(values, visible=0)
    assert masked == [MASK_CHAR * 20, MASK_CHAR * 3, ""]
    assert all(is_masked(m) for m in masked[:2])


@pytest.mark.parametrize("visible", [-1, -100])
def test_mask_all_negative_visible_raises_value_error(visible: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mask_all(["sk_live_abcdef123456"], visible=visible)


def test_mask_all_negative_visible_raises_even_for_none_and_empty_entries() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        mask_all([None, ""], visible=-1)


def test_mask_all_negative_visible_does_not_raise_for_empty_list() -> None:
    assert mask_all([], visible=-1) == []
