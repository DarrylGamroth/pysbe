"""Validation scaffolding for parser options and schema checks."""

from __future__ import annotations


class ValidationError(ValueError):
    """Raised when a schema validation error is encountered."""


def validate_schema() -> None:
    """Validate a parsed schema model (Phase 1)."""

    raise NotImplementedError("Schema validation is implemented in Phase 1")
