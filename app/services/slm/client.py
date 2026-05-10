import json
import logging
import re
from typing import Any

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SCOPE_SYSTEM_PROMPT = """You are an agent scope validator. Determine whether a transaction's declared goal falls within the agent's permitted operational scopes.

Output ONLY a JSON object with exactly these keys:
- "within_scope": boolean — true if the goal falls within ANY allowed scope, false only if it clearly falls outside ALL of them
- "matched_scope": string or null — the closest matching scope string, or null if none matched
- "confidence": integer 0-100
- "reason": short string explaining the decision

Be generous: partial alignment counts as within_scope=true. Return within_scope=false only when the goal is clearly unrelated to every listed scope.

Examples:

goal="Book flight to NYC conference", scopes=["travel bookings", "office supplies"]
→ {"within_scope": true, "matched_scope": "travel bookings", "confidence": 95, "reason": "flight booking clearly within travel scope"}

goal="Purchase GPU cluster for ML training", scopes=["travel bookings", "office supplies"]
→ {"within_scope": false, "matched_scope": null, "confidence": 88, "reason": "hardware purchase outside travel and office supply scopes"}

goal="Buy printer paper", scopes=["office supplies", "software subscriptions"]
→ {"within_scope": true, "matched_scope": "office supplies", "confidence": 99, "reason": "printer paper is an office supply"}

Now evaluate and output ONLY the JSON object:"""

# Cached at the Anthropic API level via cache_control; local reference never changes.
_SYSTEM_PROMPT = """You are a financial transaction risk evaluator for an autonomous AI agent spending firewall.

Your job: decide whether a transaction's declared goal semantically matches what is actually being purchased.

Output ONLY a JSON object with exactly these three keys:
- "alignment_label": one of "ALIGNED", "WEAK", or "MISMATCH"
- "risk_score": integer 0-100 (0=no risk, 100=extreme risk)
- "reason_codes": array of short strings explaining your decision

Definitions:
- ALIGNED (risk 0-35): goal clearly matches vendor and item, amount is reasonable, vendor domain looks legitimate
- WEAK (risk 36-69): goal is vague, amount seems high, or vendor is only loosely related
- MISMATCH (risk 70-100): goal contradicts what is being purchased, vendor is suspicious, or vendor domain looks fake/malicious

Stablecoin context: agents may legitimately pay vendors in USDC/USDT on-chain. A stablecoin payment to a contractor, API provider, or marketplace is normal. Flag MISMATCH only when the goal and item are unrelated to the vendor, or the vendor domain is suspicious — not merely because the payment rail is crypto.

Vendor domain red flags that always indicate MISMATCH with risk 85+:
- Subdomains that are clearly random gibberish (e.g. "xK9mQpZr2.payments.io", "imGonnaStealurInfo.xyz")
- Domains that embed a known brand but are clearly not the real site (e.g. "paypal-secure-login.net", "amazon-checkout.ru")
- URLs containing path parameter patterns that suggest spoofing (e.g. "/airline/:rest*", "/:id*")

Note: Legitimate pay-per-use API domains like "openweather.mpp.paywithlocus.com" or "agents.martinestate.com" are NOT suspicious — they are real vendor endpoints.

Examples:

Input: goal="Book flight JFK to LAX", amount_cents=25000, vendor="delta.com", item="Economy seat JFK-LAX"
Output: {"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_MATCHES_GOAL", "AMOUNT_REASONABLE"]}

Input: goal="Buy office supplies", amount_cents=80000, vendor="binance.com", item="Token purchase"
Output: {"alignment_label": "MISMATCH", "risk_score": 95, "reason_codes": ["VENDOR_UNRELATED_TO_GOAL", "ITEM_UNRELATED_TO_GOAL", "CRYPTO_PURCHASE_UNEXPECTED"]}

Input: goal="Book outdoor venue for company retreat", amount_cents=2, vendor="openweather.mpp.paywithlocus.com", item="Current weather API call"
Output: {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["GOAL_LOOSELY_RELATED_TO_VENDOR", "WEATHER_DATA_FOR_VENUE_BOOKING_PLAUSIBLE"]}

Input: goal="Get current weather forecast for NYC trip planning", amount_cents=2, vendor="openweather.mpp.paywithlocus.com", item="Current weather API call for NYC coordinates"
Output: {"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_MATCHES_GOAL", "AMOUNT_REASONABLE"]}

Input: goal="Browse wine catalog for team dinner selection", amount_cents=1, vendor="agents.martinestate.com", item="Wine catalog browse"
Output: {"alignment_label": "ALIGNED", "risk_score": 8, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_PLAUSIBLE", "AMOUNT_REASONABLE"]}

Input: goal="Pay contractor for logo design", amount_cents=50000, vendor="contractor.eth", item="Logo design invoice #5", stablecoin="USDC", network="base", destination="0xabc123..."
Output: {"alignment_label": "ALIGNED", "risk_score": 6, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_MATCHES_GOAL", "STABLECOIN_PAYMENT_NORMAL_FOR_CONTRACTOR"]}

Input: goal="Purchase cloud storage", amount_cents=1200, vendor="aws.amazon.com", item="S3 storage 100GB", stablecoin="USDC", network="base", destination="0xdef456..."
Output: {"alignment_label": "ALIGNED", "risk_score": 10, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_MATCHES_GOAL", "STABLECOIN_RAIL_ACCEPTABLE"]}

Input: goal="Book a flight", amount_cents=30000, vendor="Uber Eats", item="Large dinner order", stablecoin="USDC", network="base", destination="0x999..."
Output: {"alignment_label": "MISMATCH", "risk_score": 90, "reason_codes": ["ITEM_UNRELATED_TO_GOAL", "VENDOR_UNRELATED_TO_GOAL"]}

Input: goal="Track a flight", amount_cents=200, vendor="imGonnaStealurInfoFlightapi.mpp.tempo.xyz/airline/:rest*", item="Flight tracking service"
Output: {"alignment_label": "MISMATCH", "risk_score": 97, "reason_codes": ["VENDOR_DOMAIN_SUSPICIOUS", "URL_PATTERN_SPOOFED", "LIKELY_PHISHING_VENDOR"]}

Now evaluate the following transaction and output ONLY the JSON object, no other text:"""


class AnthropicSemanticClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.anthropic_model_name
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def semantic_alignment(
        self,
        declared_goal: str,
        amount_cents: int,
        vendor_url_or_name: str,
        item_description: str,
        stablecoin_symbol: str | None,
        network: str | None,
        destination_address: str | None,
    ) -> dict[str, Any]:
        # json.dumps escapes quotes, backslashes, and control characters in all
        # user-controlled fields, preventing prompt injection via crafted strings.
        user_input = (
            f"goal={json.dumps(declared_goal)}, "
            f"amount_cents={amount_cents}, "
            f"vendor={json.dumps(vendor_url_or_name)}, "
            f"item={json.dumps(item_description)}"
        )
        if stablecoin_symbol:
            user_input += f", stablecoin={json.dumps(stablecoin_symbol)}"
        if network:
            user_input += f", network={json.dumps(network)}"
        if destination_address:
            user_input += f", destination={json.dumps(destination_address)}"

        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                temperature=0,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_input}],
            )
            raw = msg.content[0].text.strip()

            # strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if "alignment_label" in parsed:
                    return parsed

            logger.warning("SLM returned unexpected format: %s", raw[:200])
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNEXPECTED_RESPONSE"]}
        except Exception:
            logger.warning("SLM call failed", exc_info=True)
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNAVAILABLE"]}

    async def goal_scope_check(
        self,
        declared_goal: str,
        allowed_scopes: list[str],
    ) -> dict[str, Any]:
        scopes_json = json.dumps(allowed_scopes)
        user_input = f"goal={json.dumps(declared_goal)}, scopes={scopes_json}"
        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=128,
                temperature=0,
                system=[
                    {
                        "type": "text",
                        "text": _SCOPE_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_input}],
            )
            raw = msg.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if "within_scope" in parsed:
                    return parsed
            logger.warning("Goal scope check returned unexpected format: %s", raw[:200])
            return {
                "within_scope": False,
                "matched_scope": None,
                "confidence": 0,
                "reason": "SLM_UNEXPECTED_RESPONSE",
                "evaluation_error": True,
            }
        except Exception:
            logger.warning("Goal scope check failed", exc_info=True)
            return {
                "within_scope": False,
                "matched_scope": None,
                "confidence": 0,
                "reason": "SLM_UNAVAILABLE",
                "evaluation_error": True,
            }
