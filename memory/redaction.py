"""Sensitive data redaction for durable semantic memory."""

from __future__ import annotations

import re

from memory.models import RedactionResult


PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")),
    ("secret", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("cookie", re.compile(r"(?i)(cookie|sessionid|session_token)\s*[:=]\s*[^;\s]+")),
]


def redact_text(text: str) -> RedactionResult:
    output = text
    markers: list[str] = []
    for name, pattern in PATTERNS:
        replacement = f"[REDACTED:{name}]"
        output, count = pattern.subn(replacement, output)
        if count:
            markers.append(name)
    return RedactionResult(text=output, redacted=bool(markers), markers=markers)
