"""Runtime error types."""


class SbeRuntimeError(RuntimeError):
    """Base runtime error for pysbe codec operations."""


class BufferTypeError(SbeRuntimeError, TypeError):
    """Raised when an unsupported buffer type is provided."""


class BufferBoundsError(SbeRuntimeError, IndexError):
    """Raised when a buffer access is out of bounds."""


class CursorStateError(SbeRuntimeError):
    """Raised when flyweight/group cursor state is invalid."""
