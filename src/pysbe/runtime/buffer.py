"""Buffer abstraction scaffolding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionPointer:
    """Shared position pointer for group/var-data traversal."""

    value: int = 0
