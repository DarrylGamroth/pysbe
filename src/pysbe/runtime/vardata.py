"""Variable-length data read/write helpers."""

from __future__ import annotations

from pysbe.runtime.buffer import BufferLike, ensure_capacity, slice_view, to_memoryview
from pysbe.runtime.primitives import primitive_size, read_primitive, write_primitive


def read_vardata(
    buffer: BufferLike,
    position: int,
    *,
    length_type: str = "uint8",
    byte_order: str = "littleEndian",
) -> tuple[memoryview, int]:
    """Read var-data at position and return `(view, next_position)`."""

    view = to_memoryview(buffer, writable=False)
    length = int(read_primitive(view, position, length_type, byte_order=byte_order))
    length_size = primitive_size(length_type)
    data_offset = position + length_size
    ensure_capacity(view, data_offset, length)
    return slice_view(view, data_offset, length), data_offset + length


def write_vardata(
    buffer: BufferLike,
    position: int,
    data: bytes | bytearray | memoryview,
    *,
    length_type: str = "uint8",
    byte_order: str = "littleEndian",
) -> int:
    """Write var-data at position and return next position."""

    target = to_memoryview(buffer, writable=True)
    source = to_memoryview(data, writable=False)
    length = len(source)

    write_primitive(target, position, length_type, length, byte_order=byte_order)
    length_size = primitive_size(length_type)
    data_offset = position + length_size
    ensure_capacity(target, data_offset, length)
    target[data_offset : data_offset + length] = source
    return data_offset + length
