from app.domains.pipeline.services.pipeline_event_service import sanitize_pipeline_payload


def test_sanitize_pipeline_payload_redacts_sensitive_fields_and_truncates_text() -> None:
    payload = {
        "token": "super-secret-token",
        "nested": {
            "api_key": "sk-test",
            "question": "A" * 400,
        },
        "content": "B" * 500,
        "list_items": list(range(60)),
        "trace": "password: hunter2",
    }

    sanitized = sanitize_pipeline_payload(payload)

    assert isinstance(sanitized, dict)
    assert sanitized["token"] == "***"
    assert sanitized["nested"]["api_key"] == "***"
    assert isinstance(sanitized["nested"]["question"], str)
    assert sanitized["nested"]["question"].endswith("[truncated]")
    assert isinstance(sanitized["content"], str)
    assert sanitized["content"].endswith("[truncated]")
    assert isinstance(sanitized["list_items"], list)
    assert len(sanitized["list_items"]) == 51
    assert sanitized["trace"] == "password=***"
