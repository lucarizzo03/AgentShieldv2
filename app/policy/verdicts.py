from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["SAFE", "SUSPICIOUS", "MALICIOUS"]


@dataclass(slots=True)
class CheckResult:
    hard_deny: bool = False
    suspicious: bool = False
    reasons: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)


@dataclass(slots=True)
class TriangulationResult:
    verdict: Verdict
    reasons: list[str]
    quantitative_result: dict
    policy_result: dict
    semantic_result: dict

