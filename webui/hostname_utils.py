from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")
_STATIC_INVALID_RE = re.compile(r"[^a-z0-9-]")
_STATIC_VALID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MULTI_DASH_RE = re.compile(r"-{2,}")


def normalize_pretty_hostname(value: str, max_length: int = 64) -> str:
    if not isinstance(value, str):
        return ""

    normalized = _WHITESPACE_RE.sub(" ", value.strip())
    if not normalized:
        return ""

    if max_length > 0 and len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip()
    return normalized


def normalize_static_hostname(value: str) -> str:
    pretty = normalize_pretty_hostname(value)
    if not pretty:
        return ""

    candidate = pretty.lower().replace("_", "-")
    candidate = _STATIC_INVALID_RE.sub("-", candidate)
    candidate = _MULTI_DASH_RE.sub("-", candidate).strip("-")

    if not candidate or len(candidate) > 63:
        return ""
    if not _STATIC_VALID_RE.match(candidate):
        return ""
    return candidate
