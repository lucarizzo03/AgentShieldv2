from typing import Any

import httpx

from app.core.config import get_settings


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
        payload = {
            "model": self._model,
            "prompt": (
                "Return strict JSON only with keys alignment_label(ALIGNED|WEAK|MISMATCH), "
                "risk_score(0-100), reason_codes(list). "
                f"goal={declared_goal!r}, amount_cents={amount_cents}, vendor={vendor_url_or_name!r}, "
                f"item={item_description!r}, stablecoin_symbol={stablecoin_symbol!r}, "
                f"network={network!r}, destination_address={destination_address!r}"
            ),
            "stream": False,
            "format": "json",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", {})
            if isinstance(raw, dict):
                return raw
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_NONJSON_RESPONSE"]}
        except Exception:
            return {"alignment_label": "WEAK", "risk_score": 55, "reason_codes": ["SLM_UNAVAILABLE"]}

