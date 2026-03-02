"""Flyweight base class scaffolding."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Flyweight:
    """Base flyweight wrapper over a byte buffer."""

    buffer: memoryview
    offset: int
