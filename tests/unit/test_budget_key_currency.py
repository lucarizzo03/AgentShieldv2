"""The budget key a spend is reserved against must be scoped by currency and
must be the very same key the HITL commit / reconciler paths recompute, or a
reservation taken in one place can never be found or released in another."""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.models.agent import Agent
from app.policy.checks.quantitative import (
    commit_budget_spend,
    daily_budget_key,
    rollback_budget_reservation,
    run_quantitative_checks,
)

REDIS_URL = "redis://localhost:6379/1"


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


def _agent(agent_id: str, currency: str = "USD", **kwargs) -> Agent:
    defaults = {
        "agent_id": agent_id,
        "currency": currency,
        "daily_budget_limit_cents": 10_000,
        "blocked_vendors": [],
        "allowed_stablecoins": ["USDC"],
        "allowed_networks": ["base"],
        "allowed_destination_addresses": [],
        "blocked_destination_addresses": [],
        "allowed_scopes": [],
    }
    defaults.update(kwargs)
    return Agent(**defaults)


async def _reserve(redis, agent, amount_cents, asset_type="FIAT", fp="fp"):
    return await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=amount_cents, asset_type=asset_type,
        network=None, destination_address=None, fingerprint=f"{fp}-{amount_cents}",
    )


def test_key_layout_has_a_currency_segment_between_asset_type_and_date() -> None:
    moment = datetime(2026, 1, 2, tzinfo=UTC)
    assert daily_budget_key("a1", "FIAT", moment, currency="EUR") == (
        "budget:daily:a1:FIAT:EUR:2026-01-02"
    )
    assert daily_budget_key("a1", "FIAT", moment) == "budget:daily:a1:FIAT:USD:2026-01-02"


def test_key_normalises_currency_case_and_padding() -> None:
    moment = datetime(2026, 1, 2, tzinfo=UTC)
    assert daily_budget_key("a1", "FIAT", moment, currency=" eur ") == (
        daily_budget_key("a1", "FIAT", moment, currency="EUR")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("currency", ["USD", "EUR", "jpy"])
async def test_reservation_key_matches_daily_budget_key(redis, currency) -> None:
    agent = _agent(f"bk-match-{currency}", currency=currency)
    expected = daily_budget_key(agent.agent_id, "FIAT", currency=currency)
    await redis.delete(expected)

    check = await _reserve(redis, agent, 500)

    assert check.context["budget_key"] == expected
    assert int(await redis.get(expected)) == 500
    await redis.delete(expected, check.context["loop_key"])


@pytest.mark.asyncio
async def test_reservations_in_different_currencies_do_not_share_a_counter(redis) -> None:
    usd_agent = _agent("bk-split", currency="USD", daily_budget_limit_cents=1_000)
    eur_agent = _agent("bk-split", currency="EUR", daily_budget_limit_cents=1_000)
    usd_key = daily_budget_key("bk-split", "FIAT", currency="USD")
    eur_key = daily_budget_key("bk-split", "FIAT", currency="EUR")
    await redis.delete(usd_key, eur_key)

    usd = await _reserve(redis, usd_agent, 800, fp="usd")
    eur = await _reserve(redis, eur_agent, 800, fp="eur")

    assert usd.hard_deny is False and eur.hard_deny is False
    assert usd.context["budget_key"] != eur.context["budget_key"]
    assert int(await redis.get(usd_key)) == 800
    assert int(await redis.get(eur_key)) == 800

    # A second USD spend is judged against USD spend only.
    usd2 = await _reserve(redis, usd_agent, 300, fp="usd2")
    assert usd2.hard_deny is True
    assert "BUDGET_DAILY_LIMIT_EXCEEDED" in usd2.reasons
    assert int(await redis.get(eur_key)) == 800

    await redis.delete(
        usd_key, eur_key, usd.context["loop_key"], eur.context["loop_key"],
    )


@pytest.mark.asyncio
async def test_hitl_commit_lands_on_the_same_key_as_the_reservation(redis) -> None:
    """SUSPICIOUS spends are rolled back and later re-committed by the HITL
    approve path via commit_budget_spend; both must address one counter."""
    agent = _agent("bk-hitl", currency="EUR", daily_budget_limit_cents=1_000)
    key = daily_budget_key(agent.agent_id, "FIAT", currency="EUR")
    await redis.delete(key)

    check = await _reserve(redis, agent, 600)
    assert int(await redis.get(key)) == 600
    await rollback_budget_reservation(redis, check.context["budget_key"], 600)
    assert int(await redis.get(key) or 0) == 0

    committed, before = await commit_budget_spend(
        redis, agent.agent_id, "FIAT", 600, agent.daily_budget_limit_cents, currency="EUR",
    )
    assert committed is True and before == 0
    assert int(await redis.get(key)) == 600

    # The commit is visible to the next reservation on the same counter.
    denied = await _reserve(redis, agent, 500, fp="after")
    assert denied.hard_deny is True
    assert int(await redis.get(key)) == 600

    await redis.delete(key, check.context["loop_key"])
