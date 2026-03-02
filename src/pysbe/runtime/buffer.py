"""Buffer adapters and bounds helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from pysbe.runtime.errors import BufferBoundsError, BufferTypeError

BufferLike = bytearray | bytes | memoryview | npt.NDArray[np.generic]


@dataclass
class PositionPointer:
    """Shared position pointer for group/var-data traversal."""

    value: int = 0

    def get(self) -> int:
        """Return current position."""

        return self.value

    def set(self, position: int) -> None:
        """Set current position."""

        self.value = position

    def advance(self, delta: int) -> int:
        """Advance position by delta and return new position."""

        self.value += delta
        return self.value


def to_memoryview(buffer: BufferLike, *, writable: bool = False) -> memoryview:
    """Adapt buffer-protocol value to a `memoryview` of bytes."""

    if isinstance(buffer, memoryview):
        view = buffer.cast("B")
    elif isinstance(buffer, np.ndarray):
        if not buffer.flags["C_CONTIGUOUS"]:
            raise BufferTypeError("numpy buffer must be C-contiguous")
        array_uint8: npt.NDArray[np.uint8] = buffer.view(np.uint8).reshape(-1)
        view = array_uint8.data.cast("B")
    elif isinstance(buffer, (bytearray, bytes)):
        view = memoryview(buffer).cast("B")
    else:
        raise BufferTypeError(f"unsupported buffer type: {type(buffer)!r}")

    if writable and view.readonly:
        raise BufferTypeError("buffer is read-only, writable buffer required")
    return view


def ensure_capacity(view: memoryview, offset: int, size: int) -> None:
    """Ensure `[offset, offset + size)` lies within `view`."""

    if offset < 0 or size < 0:
        raise BufferBoundsError(f"negative offset/size not allowed: offset={offset}, size={size}")
    if offset + size > len(view):
        raise BufferBoundsError(
            f"buffer access out of bounds: offset={offset}, size={size}, len={len(view)}"
        )


def slice_view(view: memoryview, offset: int, size: int) -> memoryview:
    """Return a bounds-checked memoryview slice."""

    ensure_capacity(view, offset, size)
    return view[offset : offset + size]


def to_numpy_uint8(
    buffer: BufferLike,
    *,
    writable: bool = False,
) -> npt.NDArray[np.uint8]:
    """Return a zero-copy uint8 NumPy view over the input buffer."""

    if isinstance(buffer, np.ndarray):
        if not buffer.flags["C_CONTIGUOUS"]:
            raise BufferTypeError("numpy buffer must be C-contiguous")
        array_view = buffer.view(np.uint8).reshape(-1)
        if writable and not array_view.flags["WRITEABLE"]:
            raise BufferTypeError("numpy buffer is read-only")
        return array_view

    buffer_view = to_memoryview(buffer, writable=writable)
    array = np.frombuffer(buffer_view, dtype=np.uint8)
    if writable and not array.flags["WRITEABLE"]:
        raise BufferTypeError("buffer is read-only, writable buffer required")
    return array


def shares_memory(left: Any, right: Any) -> bool:
    """Return whether two arrays/buffers share memory according to NumPy."""

    left_array = left if isinstance(left, np.ndarray) else to_numpy_uint8(left)
    right_array = right if isinstance(right, np.ndarray) else to_numpy_uint8(right)
    return bool(np.shares_memory(left_array, right_array))
