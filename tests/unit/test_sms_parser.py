from app.services.hitl.sms_parser import parse_sms_decision


def test_parse_sms_approve() -> None:
    parsed = parse_sms_decision("APPROVE req_abc123")
    assert parsed == ("APPROVE", "req_abc123")


def test_parse_sms_deny_case_insensitive() -> None:
    parsed = parse_sms_decision("deny REQ_77")
    assert parsed == ("DENY", "REQ_77")


def test_parse_sms_invalid_format() -> None:
    parsed = parse_sms_decision("approve")
    assert parsed is None

