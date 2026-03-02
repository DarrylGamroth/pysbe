"""Repeating-group helper utilities."""

from __future__ import annotations

from pysbe.runtime.flyweight import GroupFlyweight


def next_group_entry(group: GroupFlyweight) -> GroupFlyweight:
    """Advance and return the group cursor."""

    return group.next()
