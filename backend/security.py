"""Secret redaction and safe logging helpers.

Failure memories and execution traces are persisted and displayed, so anything
that flows into them must be sanitised first. This module implements a
best-effort, pattern-based redactor. It is intentionally conservative: when in
doubt, it redacts.

It never logs environment values; it only logs whether a key is present.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Patterns that commonly denote credentials or bearer tokens.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bearer / Basic auth headers. Must run *before* the generic key=value rule,
    # otherwise "Authorization: Bearer <token>" would only redact the word
    # "Bearer" and leave the token itself exposed.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 [REDACTED]"),
    # key=value / key: value for common secret-ish names
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|authorization|"
            r"access[_-]?key|private[_-]?key|client[_-]?secret)\b"
            r"(\s*[:=]\s*)([\"']?)([^\s\"',;}]+)"
        ),
        r"\1\2\3[REDACTED]",
    ),
    # OpenAI-style secret keys
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_KEY]"),
    # URLs containing credentials: scheme://user:pass@host
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s:@]+@"), r"\1[REDACTED]@"),
    # Long opaque hex/base64 blobs (32+ chars) that look like tokens
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "[REDACTED]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{48,}\b"), "[REDACTED]"),
)

_MASK = "[REDACTED]"


class SecretRedactor:
    """Redacts secret-looking substrings from text and structured values."""

    def __init__(self, extra_secrets: Iterable[str] | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self._extra: list[str] = []
        if extra_secrets:
            for secret in extra_secrets:
                if secret and len(secret) >= 4:
                    self._extra.append(secret)

    def redact(self, text: str) -> str:
        if not self.enabled or not isinstance(text, str) or not text:
            return text
        redacted = text
        for literal in self._extra:
            redacted = redacted.replace(literal, _MASK)
        for pattern, replacement in _PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def redact_mapping(self, data: dict) -> dict:
        """Recursively redact string values (keys are preserved)."""
        return _walk(data, self.redact)


def _walk(value, redact):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _walk(v, redact) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(v, redact) for v in value]
    return value


def build_default_redactor(settings=None) -> SecretRedactor:
    """Build a redactor that also redacts the configured API key if present."""
    from backend.config import Settings

    if settings is None:
        settings = Settings.from_env()
    extra: list[str] = []
    if settings.llm_api_key:
        extra.append(settings.llm_api_key)
    return SecretRedactor(extra_secrets=extra, enabled=settings.redact_secrets)
