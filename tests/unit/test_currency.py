from app.models.agent import Agent
from app.policy.checks.policy_db import run_policy_checks
from app.policy.checks.quantitative import daily_budget_key
from app.policy.currency import currencies_match, minor_unit_exponent, to_major_units


def _agent(currency: str = "USD") -> Agent:
    return Agent(agent_id="agent_ccy_1", currency=currency)


def test_zero_decimal_currency_is_not_divided_by_a_hundred() -> None:
    assert minor_unit_exponent("JPY") == 0
    assert to_major_units(10_000, "JPY") == 10_000.0
    assert to_major_units(10_000, "USD") == 100.0
    assert to_major_units(10_000, "BHD") == 10.0


def test_currency_comparison_ignores_case_and_padding() -> None:
    assert currencies_match(" usd ", "USD") is True
    assert currencies_match("EUR", "USD") is False


def test_budget_keys_are_scoped_per_currency() -> None:
    usd = daily_budget_key("a1", "FIAT", currency="USD")
    eur = daily_budget_key("a1", "FIAT", currency="EUR")
    assert usd != eur
    assert daily_budget_key("a1", "FIAT", currency="usd") == usd


def test_currency_mismatch_is_hard_denied() -> None:
    result = run_policy_checks(
        agent=_agent("USD"),
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
        currency="EUR",
    )
    assert result.hard_deny is True
    assert "CURRENCY_MISMATCH" in result.reasons


def test_matching_currency_passes() -> None:
    result = run_policy_checks(
        agent=_agent("JPY"),
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
        currency="jpy",
    )
    assert "CURRENCY_MISMATCH" not in result.reasons
