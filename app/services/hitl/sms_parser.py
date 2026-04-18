import re


SMS_DECISION_PATTERN = re.compile(r"^\s*(APPROVE|DENY)\s+([A-Za-z0-9_\-]+)\s*$", re.IGNORECASE)


def parse_sms_decision(body: str) -> tuple[str, str] | None:
    match = SMS_DECISION_PATTERN.match((body or "").strip())
    if not match:
        return None
    decision = match.group(1).upper()
    request_id = match.group(2).strip()
    return decision, request_id

