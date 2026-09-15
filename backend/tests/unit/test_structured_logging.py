import json

from nexus.logging.logger import configure_logging, get_logger


def test_structured_log_contains_standard_fields(capsys) -> None:
    configure_logging("INFO")
    get_logger("test").info("test_event", request_id="req_123", status_code=200)

    event = json.loads(capsys.readouterr().out.strip())
    assert event["event"] == "test_event"
    assert event["request_id"] == "req_123"
    assert event["status_code"] == 200
    assert event["level"] == "info"
    assert "timestamp" in event


def test_sensitive_fields_are_redacted(capsys) -> None:
    configure_logging("INFO")
    get_logger("test").info(
        "security_test",
        password="SUPER_SECRET",
        access_token="TOKEN_VALUE",
        api_key="KEY_VALUE",
        safe_field="visible",
    )

    event = json.loads(capsys.readouterr().out.strip())
    assert event["password"] == "[REDACTED]"
    assert event["access_token"] == "[REDACTED]"
    assert event["api_key"] == "[REDACTED]"
    assert event["safe_field"] == "visible"
    assert "SUPER_SECRET" not in json.dumps(event)
    assert "TOKEN_VALUE" not in json.dumps(event)
    assert "KEY_VALUE" not in json.dumps(event)
