"""IR model scaffolding aligned with the SBE token pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IrToken:
    """Placeholder IR token type for Phase 2 development."""

    name: str
