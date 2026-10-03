"""Secret redaction for everything observability prints or persists.

Applied by the log schema (every log line: stdout + DB) and by span content capture
(prompts, responses, tool payloads). Two layers: the literal *values* of configured
secrets (exact, format-agnostic) and regex *shapes* of well-known token formats
(catches secrets we were never told about, e.g. a key pasted into an email)."""

import os
import re
from functools import lru_cache
from typing import Any

MASK = "[REDACTED]"

_SECRET_FIELDS = (
    "telegram_bot_token", "api_token", "gemini_api_key", "anthropic_api_key",
    "groq_api_key", "gmail_client_secret", "claude_code_oauth_token",
)
_SECRET_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD")
_MIN_SECRET_LEN = 12  # shorter values collide with ordinary text

_PATTERNS = (
    re.compile(r"(?<![0-9])\d{6,12}:[A-Za-z0-9_-]{30,}"),  # Telegram bot token (follows "bot")
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),   # Authorization: Bearer …
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),                 # Google API key
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),             # Anthropic key / Claude OAuth token
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),                  # Groq
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),            # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_.-]{20,}"),             # Google OAuth access token
    re.compile(r"\b1//[A-Za-z0-9_-]{30,}"),                 # Google OAuth refresh token
)


@lru_cache(maxsize=1)
def secret_values() -> tuple[str, ...]:
    """Configured secret values, longest first (a secret containing another masks whole)."""
    values: set[str] = set()
    try:
        from app.config import get_settings

        settings = get_settings()
        values.update(str(getattr(settings, f, "") or "") for f in _SECRET_FIELDS)
        for key, value in (settings.model_extra or {}).items():
            if key.upper().endswith(_SECRET_SUFFIXES):
                values.add(str(value or ""))
    except Exception:  # settings unavailable — the env scan below still runs
        pass
    for key, value in os.environ.items():
        if key.upper().endswith(_SECRET_SUFFIXES):
            values.add(value)
    return tuple(sorted((v for v in values if len(v) >= _MIN_SECRET_LEN), key=len, reverse=True))


def redact(text: Any) -> Any:
    """Mask secrets in a string; non-strings pass through unchanged."""
    if not isinstance(text, str) or not text:
        return text
    for value in secret_values():
        if value in text:
            text = text.replace(value, MASK)
    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def redact_obj(value: Any) -> Any:
    """`redact` applied recursively through dicts, lists and tuples."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_obj(v) for v in value]
    return value
