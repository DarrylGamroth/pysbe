"""Flyweight runtime bases for message/composite/group/var-data wrappers."""

from __future__ import annotations

from dataclasses import dataclass, field

from pysbe.runtime.buffer import BufferLike, PositionPointer, to_memoryview
from pysbe.runtime.errors import CursorStateError


@dataclass
class Flyweight:
    """Base flyweight wrapper over a byte buffer."""

    buffer: memoryview
    offset: int = 0

    @classmethod
    def wrap(cls, buffer: BufferLike, offset: int = 0) -> Flyweight:
        """Construct a flyweight over an existing buffer."""

        return cls(buffer=to_memoryview(buffer, writable=False), offset=offset)

    def wrap_into(
        self,
        buffer: BufferLike,
        offset: int = 0,
        *,
        writable: bool = False,
    ) -> Flyweight:
        """Rebind this flyweight to another buffer/offset."""

        self.buffer = to_memoryview(buffer, writable=writable)
        self.offset = offset
        return self


@dataclass
class CompositeFlyweight(Flyweight):
    """Base composite flyweight."""


@dataclass
class MessageFlyweight(Flyweight):
    """Base message flyweight with shared position state."""

    acting_version: int = 0
    acting_block_length: int = 0
    position_ptr: PositionPointer = field(default_factory=PositionPointer)

    @classmethod
    def wrap(
        cls,
        buffer: BufferLike,
        offset: int = 0,
        *,
        acting_block_length: int = 0,
        acting_version: int = 0,
    ) -> MessageFlyweight:
        """Construct message flyweight and initialize position pointer."""

        instance = cls(
            buffer=to_memoryview(buffer, writable=False),
            offset=offset,
            acting_block_length=acting_block_length,
            acting_version=acting_version,
            position_ptr=PositionPointer(offset + acting_block_length),
        )
        return instance

    @property
    def position(self) -> int:
        """Current traversal position."""

        return self.position_ptr.get()

    @position.setter
    def position(self, value: int) -> None:
        self.position_ptr.set(value)

    def rewind(self) -> int:
        """Rewind position to start of variable-length region."""

        self.position = self.offset + self.acting_block_length
        return self.position


@dataclass
class GroupFlyweight(Flyweight):
    """Base repeating-group flyweight cursor."""

    position_ptr: PositionPointer = field(default_factory=PositionPointer)
    count: int = 0
    index: int = 0
    block_length: int = 0

    def wrap_group(
        self,
        buffer: BufferLike,
        *,
        offset: int,
        count: int,
        block_length: int,
        position_ptr: PositionPointer,
    ) -> GroupFlyweight:
        """Initialize repeating group cursor state."""

        self.buffer = to_memoryview(buffer, writable=False)
        self.offset = offset
        self.count = count
        self.index = 0
        self.block_length = block_length
        self.position_ptr = position_ptr
        return self

    def __iter__(self) -> GroupFlyweight:
        return self

    def __next__(self) -> GroupFlyweight:
        if self.index >= self.count:
            raise StopIteration
        self.next()
        return self

    def next(self) -> GroupFlyweight:
        """Advance to next group element."""

        if self.index >= self.count:
            raise CursorStateError("group cursor index >= count")
        self.offset = self.position_ptr.get()
        self.position_ptr.advance(self.block_length)
        self.index += 1
        return self


@dataclass
class VarDataFlyweight(Flyweight):
    """Base var-data flyweight bound to a shared position pointer."""

    position_ptr: PositionPointer = field(default_factory=PositionPointer)

    def wrap_vardata(
        self,
        buffer: BufferLike,
        *,
        offset: int,
        position_ptr: PositionPointer,
    ) -> VarDataFlyweight:
        """Initialize var-data cursor state."""

        self.buffer = to_memoryview(buffer, writable=False)
        self.offset = offset
        self.position_ptr = position_ptr
        return self
