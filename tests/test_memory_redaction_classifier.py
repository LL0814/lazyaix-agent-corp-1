def test_redacts_openai_style_secret():
    from memory.redaction import redact_text

    result = redact_text("api key is sk-abcdefghijklmnopqrstuvwxyz123456")

    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result.text
    assert "[REDACTED:secret]" in result.text
    assert result.redacted is True


def test_redacts_bearer_token():
    from memory.redaction import redact_text

    result = redact_text("Authorization: Bearer abc.def.ghi")

    assert "abc.def.ghi" not in result.text
    assert "[REDACTED:bearer_token]" in result.text


def test_redacts_private_key_block():
    from memory.redaction import redact_text

    result = redact_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----")

    assert "BEGIN PRIVATE KEY" not in result.text
    assert "[REDACTED:private_key]" in result.text


def test_redacts_cookie_like_secret():
    from memory.redaction import redact_text

    result = redact_text("cookie=sessionid=abc123")

    assert "abc123" not in result.text
    assert "[REDACTED:cookie]" in result.text


def test_classifies_stable_preference_as_semantic():
    from memory.classifier import classify_memory_candidate
    from memory.models import MemoryKind

    result = classify_memory_candidate("用户喜欢安静、交通方便的酒店")

    assert result.should_remember is True
    assert result.kind == MemoryKind.SEMANTIC
    assert result.importance >= 0.6


def test_classifies_workflow_as_procedural():
    from memory.classifier import classify_memory_candidate
    from memory.models import MemoryKind

    result = classify_memory_candidate("以后每完成一步都写中文阶段报告并等待确认")

    assert result.should_remember is True
    assert result.kind == MemoryKind.PROCEDURAL


def test_skips_low_value_transient_message():
    from memory.classifier import classify_memory_candidate

    result = classify_memory_candidate("好的")

    assert result.should_remember is False
