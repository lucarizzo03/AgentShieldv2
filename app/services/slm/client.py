from typing import Any
import json
import re

import httpx

from app.core.config import get_settings

_SYSTEM_PROMPT = """You are a financial transaction risk evaluator for an autonomous AI agent spending firewall.

Your job: decide whether a transaction's declared goal semantically matches what is actually being purchased.

Output ONLY a JSON object with exactly these three keys:
- "alignment_label": one of "ALIGNED", "WEAK", or "MISMATCH"
- "risk_score": integer 0-100 (0=no risk, 100=extreme risk)
- "reason_codes": array of short strings explaining your decision

Definitions:
- ALIGNED (risk 0-35): goal clearly matches vendor and item, amount is reasonable
- WEAK (risk 36-69): goal is vague, or amount seems high, or vendor is only loosely related
- MISMATCH (risk 70-100): goal contradicts what is being purchased, or vendor is suspicious

Examples:

Input: goal="Book flight JFK to LAX", amount_cents=25000, vendor="delta.com", item="Economy seat JFK-LAX"
Output: {"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_MATCHES_GOAL", "AMOUNT_REASONABLE"]}

Input: goal="Buy office supplies", amount_cents=150000, vendor="crypto-exchange.io", item="Token purchase"
Output: {"alignment_label": "MISMATCH", "risk_score": 95, "reason_codes": ["VENDOR_UNRELATED_TO_GOAL", "ITEM_UNRELATED_TO_GOAL", "CRYPTO_PURCHASE_UNEXPECTED"]}

Input: goal="Purchase software tools", amount_cents=50000, vendor="notion.so", item="Notion Enterprise annual plan"
Output: {"alignment_label": "ALIGNED", "risk_score": 20, "reason_codes": ["GOAL_MATCHES_ITEM", "VENDOR_PLAUSIBLE", "AMOUNT_REASONABLE"]}

Input: goal="Pay for API access", amount_cents=500000, vendor="unknown-site.xyz", item="Premium credits"
Output: {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["VENDOR_UNRECOGNIZED", "AMOUNT_HIGH_FOR_GOAL"]}

Now evaluate the following transaction and output ONLY the JSON object, no other text:"""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract the first valid JSON object from model output."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object in the output
    match = re.search(r'\{[^{}]*"alignment_label"[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Broader search for any JSON object
    match = re.search(r'\{.*?\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


class LocalSlmClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.slm_base_url.rstrip("/")
        self._model = settings.slm_model_name

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

        payload = {
            "model": self._model,
            "system": _SYSTEM_PROMPT,
            "prompt": user_input,
            "stream": False,
            "format": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "")

            if isinstance(raw, dict):
                parsed = raw
            else:
                parsed = _extract_json(str(raw))

            if parsed and "alignment_label" in parsed:
                return parsed

            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_NONJSON_RESPONSE"]}
        except Exception:
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNAVAILABLE"]}
