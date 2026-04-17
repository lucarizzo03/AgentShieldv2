from collections import Counter

_COUNTERS = Counter()


def increment(metric_name: str) -> None:
    _COUNTERS[metric_name] += 1


def snapshot() -> dict[str, int]:
    return dict(_COUNTERS)

