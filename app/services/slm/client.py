from typing import Any

import anthropic

from app.core.config import get_settings

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

Input: goal="Track a flight", amount_cents=200, vendor="imGonnaStealurInfoFlightapi.mpp.tempo.xyz/airline/:rest*", item="Flight tracking service"
Output: {"alignment_label": "MISMATCH", "risk_score": 97, "reason_codes": ["VENDOR_DOMAIN_SUSPICIOUS", "URL_PATTERN_SPOOFED", "LIKELY_PHISHING_VENDOR"]}

Now evaluate the following transaction and output ONLY the JSON object, no other text:"""


class LocalSlmClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.slm_model_name
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
        user_input = (
            f'goal="{declared_goal}", '
            f"amount_cents={amount_cents}, "
            f'vendor="{vendor_url_or_name}", '
            f'item="{item_description}"'
        )
        if stablecoin_symbol:
            user_input += f', stablecoin="{stablecoin_symbol}"'
        if network:
            user_input += f', network="{network}"'

        try:
            msg = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_input}],
            )
            import json, re, logging
            raw = msg.content[0].text.strip()

            # strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            # find first JSON object
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                if "alignment_label" in parsed:
                    return parsed

            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNEXPECTED_RESPONSE"]}
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("SLM call failed: %s", e)
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNAVAILABLE"]}
