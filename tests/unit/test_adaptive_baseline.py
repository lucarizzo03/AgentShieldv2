"""Adaptive velocity baselines (Check A): per-agent spend, hourly-rate and
vendor-diversity norms learned from executed transactions."""
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from pydantic import ValidationError
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.models.agent import Agent
from app.policy.checks.quantitative import (
    _evaluate_adaptive_baseline,
    adaptive_baseline_key,
    daily_budget_key,
    record_adaptive_observation,
    run_quantitative_checks,
)
from app.policy.engine import run_financial_triangulation
from app.policy.provenance import engine_provenance

REDIS_URL = "redis://localhost:6379/1"
VENDOR = "hosting.example"
NORMAL_AMOUNT = 1_000


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


def _agent(agent_id: str, **kwargs) -> Agent:
    defaults = dict(
        agent_id=agent_id,
        daily_budget_limit_cents=10_000_000,
        per_txn_auto_approve_limit_cents=10_000,
        blocked_vendors=[],
        allowed_stablecoins=["USDC"],
        allowed_networks=["base"],
        allowed_destination_addresses=[],
        blocked_destination_addresses=[],
        allowed_scopes=[],
    )
    defaults.update(kwargs)
    return Agent(**defaults)


def _now() -> datetime:
    # Keep every test moment well inside the current hour so "current hour"
    # buckets stay stable for the duration of a test run.
    return datetime.now(timezone.utc).replace(minute=30, second=0, microsecond=0)


async def _clear(redis, agent: Agent, fingerprint: str) -> None:
    await redis.delete(
        adaptive_baseline_key(agent.agent_id, "FIAT", agent.currency),
        daily_budget_key(agent.agent_id, "FIAT", currency=agent.currency),
        f"loop:txn:{agent.agent_id}:{fingerprint}",
    )


async def _seed_history(
    redis,
    agent: Agent,
    *,
    days: int = 4,
    per_day: int = 6,
    amount: int = NORMAL_AMOUNT,
    vendor: str = VENDOR,
    now: datetime | None = None,
) -> int:
    """One observation per hour, `per_day` per completed day, all at `amount`."""
    now = now or _now()
    count = 0
    for day in range(1, days + 1):
        for hour in range(per_day):
            moment = (now - timedelta(days=day)).replace(hour=hour)
            await record_adaptive_observation(
                redis,
                request_id=f"hist-{agent.agent_id}-{day}-{hour}",
                agent_id=agent.agent_id,
                asset_type="FIAT",
                currency=agent.currency,
                amount_cents=amount,
                vendor=vendor,
                moment=moment,
            )
            count += 1
    return count


async def _check(redis, agent: Agent, *, amount: int, vendor: str = VENDOR, fingerprint: str):
    return await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=amount, asset_type="FIAT",
        network=None, destination_address=None, fingerprint=fingerprint,
        vendor_url_or_name=vendor,
    )


FIXED_NOW = datetime(2026, 6, 15, 12, 30, tzinfo=timezone.utc)


async def _evaluate(redis, agent: Agent, *, amount: int, vendor: str = VENDOR, moment=FIXED_NOW):
    return await _evaluate_adaptive_baseline(
        redis, agent_id=agent.agent_id, asset_type="FIAT", currency=agent.currency,
        amount_cents=amount, vendor=vendor, moment=moment,
    )


async def _record_today(redis, agent: Agent, request_id: str, *, moment, vendor: str = VENDOR) -> None:
    await record_adaptive_observation(
        redis, request_id=request_id, agent_id=agent.agent_id, asset_type="FIAT",
        currency="USD", amount_cents=NORMAL_AMOUNT, vendor=vendor, moment=moment,
    )


# ---------------------------------------------------------------------------
# Recording observations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_observation_stores_normalized_member_with_ttl(redis) -> None:
    agent = _agent("ab-record-01")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", agent.currency)
    await redis.delete(key)
    moment = _now()

    await record_adaptive_observation(
        redis, request_id="req-1", agent_id=agent.agent_id, asset_type="FIAT",
        currency="usd", amount_cents=1234, vendor="  Hosting.Example ", moment=moment,
    )

    entries = await redis.zrange(key, 0, -1, withscores=True)
    assert len(entries) == 1
    member, score = entries[0]
    assert json.loads(member) == {"amount_cents": 1234, "request_id": "req-1", "vendor": "hosting.example"}
    assert score == pytest.approx(moment.timestamp())
    window_days = get_settings().adaptive_baseline_window_days
    ttl = await redis.ttl(key)
    assert window_days * 86400 < ttl <= (window_days + 1) * 86400
    await redis.delete(key)


@pytest.mark.asyncio
async def test_record_observation_is_idempotent_per_request(redis) -> None:
    agent = _agent("ab-record-02")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", agent.currency)
    await redis.delete(key)
    first = _now()

    for moment in (first, first + timedelta(minutes=5)):
        await record_adaptive_observation(
            redis, request_id="req-dup", agent_id=agent.agent_id, asset_type="FIAT",
            currency="USD", amount_cents=500, vendor=VENDOR, moment=moment,
        )

    entries = await redis.zrange(key, 0, -1, withscores=True)
    assert len(entries) == 1
    assert entries[0][1] == pytest.approx(first.timestamp())
    await redis.delete(key)


@pytest.mark.asyncio
async def test_record_observation_prunes_outside_window_and_over_cap(redis, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "adaptive_baseline_max_observations", 20, raising=True)
    agent = _agent("ab-record-03")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", agent.currency)
    await redis.delete(key)
    now = _now()
    window = get_settings().adaptive_baseline_window_days

    await record_adaptive_observation(
        redis, request_id="stale", agent_id=agent.agent_id, asset_type="FIAT",
        currency="USD", amount_cents=500, vendor=VENDOR,
        moment=now - timedelta(days=window + 2),
    )
    for i in range(25):
        await record_adaptive_observation(
            redis, request_id=f"fresh-{i}", agent_id=agent.agent_id, asset_type="FIAT",
            currency="USD", amount_cents=500, vendor=VENDOR,
            moment=now - timedelta(hours=25 - i),
        )

    members = [json.loads(m) for m in await redis.zrange(key, 0, -1)]
    ids = [m["request_id"] for m in members]
    assert len(ids) == 20
    assert "stale" not in ids
    assert ids == [f"fresh-{i}" for i in range(5, 25)]
    await redis.delete(key)


@pytest.mark.asyncio
async def test_record_observation_is_a_noop_without_sorted_set_support() -> None:
    class _NoZset:
        pass

    await record_adaptive_observation(
        _NoZset(), request_id="x", agent_id="a", asset_type="FIAT",
        currency="USD", amount_cents=1, vendor=VENDOR,
    )


# ---------------------------------------------------------------------------
# Evaluation inside Check A
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_history_reports_insufficient_and_stays_clean(redis) -> None:
    agent = _agent("ab-eval-01")
    await _clear(redis, agent, "fp")

    check = await _check(redis, agent, amount=50_000, fingerprint="fp")

    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    assert not any(r.startswith("ADAPTIVE_") and r.endswith("_OUTLIER") for r in check.reasons)
    assert check.suspicious is False
    assert check.hard_deny is False
    ctx = check.context["adaptive_baseline"]
    assert ctx["key"] == adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    assert ctx["evaluated"] is False
    assert ctx["sample_count"] == 0
    assert ctx["historical_days"] == 0
    assert ctx["signals"] == {}
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_enough_samples_but_too_few_days_is_insufficient(redis, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "adaptive_baseline_min_samples", 20, raising=True)
    monkeypatch.setattr(get_settings(), "adaptive_baseline_min_days", 3, raising=True)
    agent = _agent("ab-eval-02")
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent, days=2, per_day=12)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT * 50, fingerprint="fp")

    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    assert check.suspicious is False
    ctx = check.context["adaptive_baseline"]
    assert ctx["sample_count"] == 24
    assert ctx["historical_days"] == 2
    assert ctx["evaluated"] is False
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_same_day_observations_do_not_count_as_historical_days(redis) -> None:
    agent = _agent("ab-eval-03")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    for i in range(30):
        await record_adaptive_observation(
            redis, request_id=f"today-{i}", agent_id=agent.agent_id, asset_type="FIAT",
            currency="USD", amount_cents=NORMAL_AMOUNT, vendor=VENDOR,
            moment=FIXED_NOW.replace(hour=i % 12, minute=i),
        )

    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT)

    assert ctx["sample_count"] == 30
    assert ctx["historical_days"] == 0
    assert ctx["evaluated"] is False
    assert reasons == ["ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY"]
    await redis.delete(key)


@pytest.mark.asyncio
async def test_normal_traffic_matches_baseline(redis) -> None:
    agent = _agent("ab-eval-04")
    await _clear(redis, agent, "fp")
    samples = await _seed_history(redis, agent)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT, fingerprint="fp")

    assert "ADAPTIVE_BASELINE_NORMAL" in check.reasons
    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" not in check.reasons
    assert check.suspicious is False
    assert check.hard_deny is False
    ctx = check.context["adaptive_baseline"]
    assert ctx["evaluated"] is True
    assert ctx["sample_count"] == samples
    assert ctx["historical_days"] == 4
    assert set(ctx["signals"]) == {"amount", "daily_spend", "hourly_rate", "vendor_diversity"}
    assert all(sig["outlier"] is False for sig in ctx["signals"].values())
    assert ctx["signals"]["amount"]["mean"] == NORMAL_AMOUNT
    assert ctx["signals"]["amount"]["observed"] == NORMAL_AMOUNT
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_amount_outlier_is_suspicious_but_never_hard_deny(redis) -> None:
    agent = _agent("ab-eval-05")
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT * 10, fingerprint="fp")

    assert "ADAPTIVE_AMOUNT_OUTLIER" in check.reasons
    assert "ADAPTIVE_BASELINE_NORMAL" not in check.reasons
    assert "ADAPTIVE_DAILY_SPEND_OUTLIER" not in check.reasons
    assert check.suspicious is True
    assert check.hard_deny is False
    signal = check.context["adaptive_baseline"]["signals"]["amount"]
    assert signal["outlier"] is True
    assert signal["observed"] == NORMAL_AMOUNT * 10
    assert signal["threshold"] == NORMAL_AMOUNT * 2  # zero-variance history → 2x mean floor
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_amount_just_above_twice_the_mean_trips_with_flat_history(redis) -> None:
    agent = _agent("ab-eval-06")
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent)

    at_threshold = await _check(redis, agent, amount=NORMAL_AMOUNT * 2, fingerprint="fp-a")
    over = await _check(redis, agent, amount=NORMAL_AMOUNT * 2 + 1, fingerprint="fp-b")

    assert "ADAPTIVE_AMOUNT_OUTLIER" not in at_threshold.reasons
    assert "ADAPTIVE_AMOUNT_OUTLIER" in over.reasons
    await _clear(redis, agent, "fp-a")
    await redis.delete(f"loop:txn:{agent.agent_id}:fp-b")


@pytest.mark.asyncio
async def test_threshold_widens_with_variance(redis, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "adaptive_baseline_z_score_threshold", 1.0, raising=True)
    agent = _agent("ab-eval-07")
    await _clear(redis, agent, "fp")
    now = _now()
    amounts = [100, 300] * 12  # mean 200, pstdev 100 → threshold max(300, 400) = 400
    for i, amount in enumerate(amounts):
        await record_adaptive_observation(
            redis, request_id=f"var-{i}", agent_id=agent.agent_id, asset_type="FIAT",
            currency="USD", amount_cents=amount, vendor=VENDOR,
            moment=(now - timedelta(days=1 + i % 4)).replace(hour=i % 6),
        )

    check = await _check(redis, agent, amount=350, fingerprint="fp")
    signal = check.context["adaptive_baseline"]["signals"]["amount"]
    assert signal["mean"] == 200
    assert signal["stddev"] == 100
    assert signal["threshold"] == 400
    assert "ADAPTIVE_AMOUNT_OUTLIER" not in check.reasons

    check = await _check(redis, agent, amount=401, fingerprint="fp")
    assert "ADAPTIVE_AMOUNT_OUTLIER" in check.reasons
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_daily_spend_outlier_includes_candidate_amount(redis) -> None:
    agent = _agent("ab-eval-08")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    await _seed_history(redis, agent, per_day=6, now=FIXED_NOW)  # 6_000 per completed day
    # Twelve normal-size purchases already executed earlier today, one per hour,
    # so neither the amount nor the hourly rate is unusual.
    for hour in range(12):
        await _record_today(redis, agent, f"today-{hour}", moment=FIXED_NOW.replace(hour=hour, minute=0))

    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT)

    daily = ctx["signals"]["daily_spend"]
    assert daily["observed"] == 13 * NORMAL_AMOUNT
    assert daily["mean"] == 6 * NORMAL_AMOUNT
    assert daily["threshold"] == 12 * NORMAL_AMOUNT
    assert daily["outlier"] is True
    assert reasons == ["ADAPTIVE_DAILY_SPEND_OUTLIER"]
    assert ctx["signals"]["hourly_rate"]["observed"] == 1
    await redis.delete(key)


@pytest.mark.asyncio
async def test_daily_spend_just_within_threshold_is_normal(redis) -> None:
    agent = _agent("ab-eval-08b")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    await _seed_history(redis, agent, per_day=6, now=FIXED_NOW)
    for hour in range(11):
        await _record_today(redis, agent, f"today-{hour}", moment=FIXED_NOW.replace(hour=hour, minute=0))

    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT)

    assert ctx["signals"]["daily_spend"]["observed"] == 12 * NORMAL_AMOUNT
    assert reasons == ["ADAPTIVE_BASELINE_NORMAL"]
    await redis.delete(key)


@pytest.mark.asyncio
async def test_hourly_rate_outlier_counts_current_hour_only(redis) -> None:
    agent = _agent("ab-eval-09")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    await _seed_history(redis, agent, now=FIXED_NOW)  # 1 per hour historically
    for i in range(4):
        await _record_today(redis, agent, f"burst-{i}", moment=FIXED_NOW.replace(minute=i))
    # Earlier today but a different hour: must not count toward the current hour.
    await _record_today(redis, agent, "earlier", moment=FIXED_NOW.replace(hour=9))

    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT)

    hourly = ctx["signals"]["hourly_rate"]
    assert hourly["observed"] == 5
    assert hourly["mean"] == 1
    assert hourly["threshold"] == 2
    assert hourly["outlier"] is True
    assert reasons == ["ADAPTIVE_HOURLY_RATE_OUTLIER"]
    await redis.delete(key)


@pytest.mark.asyncio
async def test_vendor_diversity_outlier_is_case_insensitive(redis) -> None:
    agent = _agent("ab-eval-10")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    await _seed_history(redis, agent, now=FIXED_NOW)  # 1 vendor per day historically
    for i, vendor in enumerate(["alpha.example", "beta.example"]):
        await _record_today(redis, agent, f"vendor-{i}", moment=FIXED_NOW.replace(hour=i), vendor=vendor)

    # A vendor already seen today (different case) keeps the count at 2 == 2x floor.
    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT, vendor="  ALPHA.example ")
    diversity = ctx["signals"]["vendor_diversity"]
    assert diversity["observed"] == 2
    assert diversity["mean"] == 1
    assert diversity["threshold"] == 2
    assert reasons == ["ADAPTIVE_BASELINE_NORMAL"]

    # A third distinct vendor today tips it over.
    reasons, ctx = await _evaluate(redis, agent, amount=NORMAL_AMOUNT, vendor="gamma.example")
    assert ctx["signals"]["vendor_diversity"]["observed"] == 3
    assert ctx["signals"]["vendor_diversity"]["outlier"] is True
    assert reasons == ["ADAPTIVE_VENDOR_DIVERSITY_OUTLIER"]
    await redis.delete(key)


@pytest.mark.asyncio
async def test_multiple_outliers_are_all_reported(redis) -> None:
    agent = _agent("ab-eval-10b")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await redis.delete(key)
    await _seed_history(redis, agent, now=FIXED_NOW)
    for i in range(3):
        await _record_today(redis, agent, f"burst-{i}", moment=FIXED_NOW.replace(minute=i), vendor=f"v{i}.example")

    reasons, _ = await _evaluate(redis, agent, amount=NORMAL_AMOUNT * 20, vendor="v9.example")

    assert set(reasons) == {
        "ADAPTIVE_AMOUNT_OUTLIER",
        "ADAPTIVE_DAILY_SPEND_OUTLIER",
        "ADAPTIVE_HOURLY_RATE_OUTLIER",
        "ADAPTIVE_VENDOR_DIVERSITY_OUTLIER",
    }
    await redis.delete(key)


@pytest.mark.asyncio
async def test_malformed_observations_are_ignored(redis) -> None:
    agent = _agent("ab-eval-11")
    await _clear(redis, agent, "fp")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    await _seed_history(redis, agent)
    ts = (_now() - timedelta(days=1)).timestamp()
    junk = {
        "not json": ts,
        json.dumps(["list"]): ts + 1,
        json.dumps({"amount_cents": 100, "vendor": VENDOR}): ts + 2,  # no request_id
        json.dumps({"request_id": "neg", "amount_cents": -5, "vendor": VENDOR}): ts + 3,
        json.dumps({"request_id": "bool", "amount_cents": True, "vendor": VENDOR}): ts + 4,
        json.dumps({"request_id": "str", "amount_cents": "100", "vendor": VENDOR}): ts + 5,
        json.dumps({"request_id": "novendor", "amount_cents": 100, "vendor": None}): ts + 6,
        json.dumps({"request_id": "huge", "amount_cents": 10**9, "vendor": VENDOR}): float("-inf"),
    }
    await redis.zadd(key, junk)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT, fingerprint="fp")

    ctx = check.context["adaptive_baseline"]
    assert ctx["sample_count"] == 24
    assert ctx["signals"]["amount"]["mean"] == NORMAL_AMOUNT
    assert "ADAPTIVE_BASELINE_NORMAL" in check.reasons
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_observations_outside_window_are_not_evaluated(redis) -> None:
    agent = _agent("ab-eval-12")
    await _clear(redis, agent, "fp")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")
    window = get_settings().adaptive_baseline_window_days
    old = _now() - timedelta(days=window + 2)
    stale = {
        json.dumps({"request_id": f"old-{i}", "amount_cents": NORMAL_AMOUNT, "vendor": VENDOR}):
            (old - timedelta(days=i % 5, hours=i)).timestamp()
        for i in range(30)
    }
    await redis.zadd(key, stale)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT, fingerprint="fp")

    assert check.context["adaptive_baseline"]["sample_count"] == 0
    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_baseline_is_scoped_per_agent_asset_and_currency(redis) -> None:
    agent = _agent("ab-eval-13")
    other = _agent("ab-eval-13-other")
    await _clear(redis, agent, "fp")
    await _clear(redis, other, "fp")
    await _seed_history(redis, other)

    assert adaptive_baseline_key("a", "FIAT", "usd") == "baseline:spend:a:FIAT:USD"
    assert adaptive_baseline_key("a", "FIAT", "USD") != adaptive_baseline_key("a", "STABLECOIN", "USD")
    assert adaptive_baseline_key("a", "FIAT", "USD") != adaptive_baseline_key("a", "FIAT", "EUR")

    check = await _check(redis, agent, amount=NORMAL_AMOUNT * 100, fingerprint="fp")
    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    assert check.suspicious is False
    await _clear(redis, agent, "fp")
    await _clear(redis, other, "fp")


@pytest.mark.asyncio
async def test_budget_exceeded_skips_baseline_evaluation(redis) -> None:
    agent = _agent("ab-eval-14", daily_budget_limit_cents=500)
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent)

    check = await _check(redis, agent, amount=NORMAL_AMOUNT * 100, fingerprint="fp")

    assert check.hard_deny is True
    assert "BUDGET_DAILY_LIMIT_EXCEEDED" in check.reasons
    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    assert "ADAPTIVE_AMOUNT_OUTLIER" not in check.reasons
    ctx = check.context["adaptive_baseline"]
    assert ctx["evaluated"] is False
    assert ctx["signals"] == {}
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_redis_without_sorted_sets_degrades_to_insufficient_history() -> None:
    class _MinimalRedis:
        async def eval(self, script, numkeys, *args):
            if "INCRBY" in script:
                return [1, 0, int(args[numkeys])]
            return 1

    agent = _agent("ab-eval-15")
    check = await run_quantitative_checks(
        redis=_MinimalRedis(), agent=agent, amount_cents=NORMAL_AMOUNT, asset_type="FIAT",
        network=None, destination_address=None, fingerprint="fp", vendor_url_or_name=VENDOR,
    )
    assert "ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY" in check.reasons
    assert check.suspicious is False
    assert check.context["adaptive_baseline"]["evaluated"] is False


# ---------------------------------------------------------------------------
# Engine verdicts
# ---------------------------------------------------------------------------

class _AlignedClient:
    async def semantic_alignment(self, **_kwargs) -> dict:
        return {"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["TEST"]}

    async def goal_scope_check(self, **_kwargs) -> dict:
        return {"within_scope": True, "matched_scope": "hosting", "confidence": 99}


async def _triangulate(redis, agent: Agent, amount: int, fingerprint: str):
    return await run_financial_triangulation(
        redis=redis, semantic_client=_AlignedClient(), agent=agent,
        amount_cents=amount, vendor_url_or_name=VENDOR,
        item_description="Monthly hosting", declared_goal="Pay hosting provider",
        asset_type="FIAT", stablecoin_symbol=None, network=None,
        destination_address=None, fingerprint=fingerprint,
    )


@pytest.mark.asyncio
async def test_engine_keeps_normal_traffic_safe(redis) -> None:
    agent = _agent("ab-engine-01")
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent)

    result = await _triangulate(redis, agent, NORMAL_AMOUNT, "fp")

    assert result.verdict == "SAFE"
    assert "ADAPTIVE_BASELINE_NORMAL" in result.reasons
    assert result.quantitative_result["adaptive_baseline"]["evaluated"] is True
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_engine_routes_outlier_to_hitl_not_block(redis) -> None:
    agent = _agent("ab-engine-02")
    await _clear(redis, agent, "fp")
    await _seed_history(redis, agent)

    result = await _triangulate(redis, agent, NORMAL_AMOUNT * 25, "fp")

    assert result.verdict == "SUSPICIOUS"
    assert "ADAPTIVE_AMOUNT_OUTLIER" in result.reasons
    assert "BUDGET_WITHIN_LIMIT" in result.reasons
    await _clear(redis, agent, "fp")


@pytest.mark.asyncio
async def test_engine_does_not_learn_from_evaluation_alone(redis) -> None:
    """Only executed spends feed the baseline; a check by itself must not."""
    agent = _agent("ab-engine-03")
    await _clear(redis, agent, "fp")
    key = adaptive_baseline_key(agent.agent_id, "FIAT", "USD")

    await _triangulate(redis, agent, NORMAL_AMOUNT, "fp")

    assert await redis.zcard(key) == 0
    await _clear(redis, agent, "fp")


# ---------------------------------------------------------------------------
# Config + provenance
# ---------------------------------------------------------------------------

def test_adaptive_defaults() -> None:
    settings = Settings(app_env="dev")
    assert settings.adaptive_baseline_window_days == 30
    assert settings.adaptive_baseline_min_samples == 20
    assert settings.adaptive_baseline_min_days == 3
    assert settings.adaptive_baseline_z_score_threshold == 3.0
    assert settings.adaptive_baseline_max_observations == 1000


@pytest.mark.parametrize(
    "overrides",
    [
        {"adaptive_baseline_min_samples": 50, "adaptive_baseline_max_observations": 20},
        {"adaptive_baseline_min_days": 10, "adaptive_baseline_window_days": 5},
        {"adaptive_baseline_window_days": 1},
        {"adaptive_baseline_min_samples": 0},
        {"adaptive_baseline_min_days": 0},
        {"adaptive_baseline_z_score_threshold": 0},
        {"adaptive_baseline_max_observations": 19},
    ],
)
def test_adaptive_settings_reject_inconsistent_values(overrides) -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="dev", **overrides)


def test_adaptive_settings_accept_boundary_values() -> None:
    settings = Settings(
        app_env="dev",
        adaptive_baseline_min_samples=20,
        adaptive_baseline_max_observations=20,
        adaptive_baseline_min_days=5,
        adaptive_baseline_window_days=5,
    )
    assert settings.adaptive_baseline_min_days == settings.adaptive_baseline_window_days


def test_provenance_records_adaptive_thresholds(monkeypatch) -> None:
    settings = get_settings()
    thresholds = engine_provenance()["thresholds"]
    assert thresholds["adaptive_baseline_window_days"] == settings.adaptive_baseline_window_days
    assert thresholds["adaptive_baseline_min_samples"] == settings.adaptive_baseline_min_samples
    assert thresholds["adaptive_baseline_min_days"] == settings.adaptive_baseline_min_days
    assert thresholds["adaptive_baseline_z_score_threshold"] == settings.adaptive_baseline_z_score_threshold
    assert thresholds["adaptive_baseline_max_observations"] == settings.adaptive_baseline_max_observations

    monkeypatch.setattr(settings, "adaptive_baseline_z_score_threshold", 2.5, raising=True)
    assert engine_provenance()["thresholds"]["adaptive_baseline_z_score_threshold"] == 2.5
