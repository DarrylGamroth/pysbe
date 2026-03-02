"""Primitive read/write and fixed-array views."""

from __future__ import annotations

import struct
from functools import cache
from typing import cast

import numpy as np
import numpy.typing as npt

from pysbe.runtime.buffer import BufferLike, ensure_capacity, to_memoryview
from pysbe.runtime.errors import BufferTypeError

PRIMITIVE_SIZES: dict[str, int] = {
    "char": 1,
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "int32": 4,
    "uint32": 4,
    "float": 4,
    "int64": 8,
    "uint64": 8,
    "double": 8,
}

STRUCT_CODES: dict[str, str] = {
    "char": "B",
    "int8": "b",
    "uint8": "B",
    "int16": "h",
    "uint16": "H",
    "int32": "i",
    "uint32": "I",
    "float": "f",
    "int64": "q",
    "uint64": "Q",
    "double": "d",
}

NUMPY_DTYPES: dict[str, np.dtype[np.generic]] = {
    "char": np.dtype(np.uint8),
    "int8": np.dtype(np.int8),
    "uint8": np.dtype(np.uint8),
    "int16": np.dtype(np.int16),
    "uint16": np.dtype(np.uint16),
    "int32": np.dtype(np.int32),
    "uint32": np.dtype(np.uint32),
    "float": np.dtype(np.float32),
    "int64": np.dtype(np.int64),
    "uint64": np.dtype(np.uint64),
    "double": np.dtype(np.float64),
}


def _struct_prefix(byte_order: str) -> str:
    if byte_order == "littleEndian":
        return "<"
    if byte_order == "bigEndian":
        return ">"
    raise BufferTypeError(f"unsupported byte order: {byte_order!r}")


@cache
def _primitive_struct(primitive_type: str, byte_order: str) -> struct.Struct:
    code = STRUCT_CODES.get(primitive_type)
    if code is None:
        raise BufferTypeError(f"unsupported primitive type: {primitive_type!r}")
    return struct.Struct(_struct_prefix(byte_order) + code)


def primitive_size(primitive_type: str) -> int:
    """Return primitive encoded size in bytes."""

    size = PRIMITIVE_SIZES.get(primitive_type)
    if size is None:
        raise BufferTypeError(f"unsupported primitive type: {primitive_type!r}")
    return size


def read_primitive(
    buffer: BufferLike,
    offset: int,
    primitive_type: str,
    *,
    byte_order: str = "littleEndian",
) -> int | float:
    """Read a primitive value from buffer."""

    view = to_memoryview(buffer, writable=False)
    struct_view = _primitive_struct(primitive_type, byte_order)
    ensure_capacity(view, offset, struct_view.size)
    value = struct_view.unpack_from(view, offset)[0]
    return cast(int | float, value)


def write_primitive(
    buffer: BufferLike,
    offset: int,
    primitive_type: str,
    value: int | float,
    *,
    byte_order: str = "littleEndian",
) -> None:
    """Write a primitive value into buffer."""

    view = to_memoryview(buffer, writable=True)
    struct_view = _primitive_struct(primitive_type, byte_order)
    ensure_capacity(view, offset, struct_view.size)
    struct_view.pack_into(view, offset, value)


def view_primitive_array(
    buffer: BufferLike,
    offset: int,
    primitive_type: str,
    length: int,
    *,
    byte_order: str = "littleEndian",
    writable: bool = False,
) -> npt.NDArray[np.generic]:
    """Return zero-copy NumPy view over a fixed primitive array."""

    if length < 0:
        raise BufferTypeError("array length must be non-negative")
    view = to_memoryview(buffer, writable=writable)
    primitive_dtype = NUMPY_DTYPES.get(primitive_type)
    if primitive_dtype is None:
        raise BufferTypeError(f"unsupported primitive type: {primitive_type!r}")

    size = primitive_size(primitive_type) * length
    ensure_capacity(view, offset, size)

    if byte_order == "littleEndian":
        dtype = primitive_dtype.newbyteorder("<")
    elif byte_order == "bigEndian":
        dtype = primitive_dtype.newbyteorder(">")
    else:
        raise BufferTypeError(f"unsupported byte order: {byte_order!r}")

    result = np.frombuffer(view, dtype=dtype, count=length, offset=offset)
    if writable and not result.flags["WRITEABLE"]:
        raise BufferTypeError("buffer is read-only, writable array required")
    return result
