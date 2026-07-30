"""Small redaction helpers for URLs and diagnostic text."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|authorization|password|cookie)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+")
_SECRET_PREFIX = re.compile(r"\b(?:sk|ghp|gho|xoxb|xoxp)-?[A-Za-z0-9_-]{12,}\b")


def redact_url(url: str) -> str:
    """Remove credentials, query parameters, and fragments from a URL."""

    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def redact_text(value: str) -> str:
    """Mask common secret forms in operator-visible diagnostic text."""

    value = _BEARER.sub("Bearer <redacted>", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1=<redacted>", value)
    return _SECRET_PREFIX.sub("<redacted>", value)
