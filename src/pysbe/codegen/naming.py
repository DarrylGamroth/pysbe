"""Naming and identifier sanitization helpers."""

from __future__ import annotations

import keyword
import re


def sanitize_identifier(name: str) -> str:
    """Sanitize schema names to safe Python identifiers."""

    candidate = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not candidate:
        candidate = "field"
    if candidate[0].isdigit():
        candidate = f"_{candidate}"
    if keyword.iskeyword(candidate):
        candidate = f"{candidate}_"
    return candidate


def class_name(name: str) -> str:
    """Convert an identifier-like name to PascalCase class name."""

    cleaned = sanitize_identifier(name)
    parts = [part for part in re.split(r"[_\-]+", cleaned) if part]
    if not parts:
        return "Schema"
    return "".join(part[:1].upper() + part[1:] for part in parts)
