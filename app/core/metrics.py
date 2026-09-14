"""Process-local counters and latency histograms with Prometheus exposition.

An in-process ``Counter`` that nothing scrapes cannot tell an operator the
engine is misbehaving: the signals that matter (how often the model path falls
back, how the verdict mix is drifting, how long checks take, whether budget
reservations are leaking) only become alerts once they leave the process.
Metrics are per-worker by design — Prometheus aggregates across scraped
targets, so workers must not try to share state.
"""

import threading
from collections import Counter, defaultdict, deque

# Seconds. Upper bounds of the cumulative buckets; the model calls dominate
# check latency, so the useful resolution sits between 100ms and ~10s.
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# Buckets and sums are cumulative, but quantiles need samples: keep only a
# bounded window of them so a long-lived worker cannot grow without bound.
_SAMPLE_WINDOW = 1024

_lock = threading.Lock()
_COUNTERS: Counter = Counter()
_BUCKETS: dict[str, Counter] = defaultdict(Counter)
_TOTALS: dict[str, dict[str, float]] = defaultdict(lambda: {"sum": 0.0, "count": 0.0})
_SAMPLES: dict[str, deque] = defaultdict(lambda: deque(maxlen=_SAMPLE_WINDOW))


def increment(metric_name: str, value: int = 1) -> None:
    with _lock:
        _COUNTERS[metric_name] += value


def observe(metric_name: str, seconds: float) -> None:
    """Records a latency observation for ``metric_name`` (a histogram)."""
    with _lock:
        buckets = _BUCKETS[metric_name]
        for bound in _LATENCY_BUCKETS:
            if seconds <= bound:
                buckets[bound] += 1
        totals = _TOTALS[metric_name]
        totals["sum"] += seconds
        totals["count"] += 1
        _SAMPLES[metric_name].append(seconds)


def snapshot() -> dict[str, int]:
    with _lock:
        return dict(_COUNTERS)


def histogram_snapshot() -> dict[str, dict]:
    with _lock:
        samples = {name: sorted(values) for name, values in _SAMPLES.items()}
        totals = {name: dict(values) for name, values in _TOTALS.items()}

    return {
        name: {
            "count": int(totals[name]["count"]),
            "sum": totals[name]["sum"],
            "p50": _quantile(ordered, 0.50),
            "p95": _quantile(ordered, 0.95),
            "p99": _quantile(ordered, 0.99),
        }
        for name, ordered in samples.items()
    }


def _quantile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[index]


def _prometheus_name(metric_name: str) -> str:
    return "agentshield_" + metric_name.replace(".", "_").replace("-", "_")


def render_prometheus() -> str:
    """Renders the current metrics in the Prometheus text exposition format."""
    with _lock:
        counters = dict(_COUNTERS)
        buckets = {name: dict(values) for name, values in _BUCKETS.items()}
        totals = {name: dict(values) for name, values in _TOTALS.items()}

    lines: list[str] = []
    for name in sorted(counters):
        metric = f"{_prometheus_name(name)}_total"
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {counters[name]}")

    for name in sorted(totals):
        metric = f"{_prometheus_name(name)}_seconds"
        count = int(totals[name]["count"])
        lines.append(f"# TYPE {metric} histogram")
        for bound in _LATENCY_BUCKETS:
            lines.append(f'{metric}_bucket{{le="{bound}"}} {buckets.get(name, {}).get(bound, 0)}')
        lines.append(f'{metric}_bucket{{le="+Inf"}} {count}')
        lines.append(f"{metric}_sum {totals[name]['sum']}")
        lines.append(f"{metric}_count {count}")

    return "\n".join(lines) + "\n"


def reset() -> None:
    """Test helper: clears all collected metrics."""
    with _lock:
        _COUNTERS.clear()
        _BUCKETS.clear()
        _TOTALS.clear()
        _SAMPLES.clear()
