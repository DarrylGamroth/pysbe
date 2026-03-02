"""Validation primitives used by schema parsing."""

from __future__ import annotations

import keyword
import re
import sys
from dataclasses import dataclass, field

SBE_SYMBOLIC_NAME_RE = re.compile(r"^[A-Za-z_][0-9A-Za-z_]*$")


class ValidationError(ValueError):
    """Raised when a schema validation error is encountered."""


@dataclass(frozen=True)
class ValidationOptions:
    """Controls parser validation behavior."""

    warnings_fatal: bool = False
    suppress_warnings: bool = False
    strict_names: bool = True


@dataclass
class ValidationContext:
    """Collects validation warnings and emits errors according to options."""

    options: ValidationOptions = field(default_factory=ValidationOptions)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        """Raise a validation error with a stable message."""

        raise ValidationError(message)

    def warning(self, message: str) -> None:
        """Record a warning and optionally escalate to an error."""

        if self.options.warnings_fatal:
            self.error(message)
        self.warnings.append(message)
        if not self.options.suppress_warnings:
            print(f"pysbe warning: {message}", file=sys.stderr)

    def validate_identifier(self, name: str, context: str) -> None:
        """Warn if an identifier is not valid in Python."""

        if not name.isidentifier() or keyword.iskeyword(name):
            self.warning(f"{context} name is not a valid Python identifier: {name!r}")

    def validate_symbolic_name(self, name: str, context: str) -> None:
        """Validate SBE symbolic-name shape according to the reference XSD pattern."""

        if SBE_SYMBOLIC_NAME_RE.match(name):
            return

        message = (
            f"{context} name must match SBE symbolicName pattern "
            f"[A-Za-z_][0-9A-Za-z_]*, got {name!r}"
        )
        if self.options.strict_names:
            self.error(message)
        else:
            self.warning(message)
