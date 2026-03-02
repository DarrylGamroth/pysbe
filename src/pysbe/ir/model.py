"""IR model aligned with SBE token-stream generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Signal(StrEnum):
    """Token signal types used by the SBE IR."""

    BEGIN_MESSAGE = "BEGIN_MESSAGE"
    END_MESSAGE = "END_MESSAGE"
    BEGIN_FIELD = "BEGIN_FIELD"
    END_FIELD = "END_FIELD"
    BEGIN_GROUP = "BEGIN_GROUP"
    END_GROUP = "END_GROUP"
    BEGIN_VAR_DATA = "BEGIN_VAR_DATA"
    END_VAR_DATA = "END_VAR_DATA"
    BEGIN_COMPOSITE = "BEGIN_COMPOSITE"
    END_COMPOSITE = "END_COMPOSITE"
    BEGIN_ENUM = "BEGIN_ENUM"
    END_ENUM = "END_ENUM"
    VALID_VALUE = "VALID_VALUE"
    BEGIN_SET = "BEGIN_SET"
    END_SET = "END_SET"
    CHOICE = "CHOICE"
    ENCODING = "ENCODING"


class Presence(StrEnum):
    """Field/type presence metadata."""

    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    CONSTANT = "CONSTANT"


class PrimitiveType(StrEnum):
    """Primitive wire types supported by SBE."""

    NONE = "none"
    CHAR = "char"
    INT8 = "int8"
    INT16 = "int16"
    INT32 = "int32"
    INT64 = "int64"
    UINT8 = "uint8"
    UINT16 = "uint16"
    UINT32 = "uint32"
    UINT64 = "uint64"
    FLOAT = "float"
    DOUBLE = "double"

    @classmethod
    def from_name(cls, name: str | None) -> PrimitiveType:
        """Resolve primitive type from schema name."""

        if name is None:
            return cls.NONE
        for primitive in cls:
            if primitive.value == name:
                return primitive
        return cls.NONE


@dataclass
class Encoding:
    """Encoding metadata attached to tokens."""

    primitive_type: PrimitiveType = PrimitiveType.NONE
    presence: Presence = Presence.REQUIRED
    byte_order: str = "littleEndian"
    semantic_type: str | None = None


@dataclass
class IrToken:
    """IR token."""

    signal: Signal
    name: str
    id: int = -1
    version: int = 0
    offset: int = 0
    encoded_length: int = 0
    component_token_count: int = 1
    referenced_name: str | None = None
    description: str = ""
    encoding: Encoding = field(default_factory=Encoding)


@dataclass
class IrSchema:
    """Schema-level IR container."""

    package_name: str
    id: int
    version: int
    byte_order: str
    header_tokens: list[IrToken]
    messages_by_id: dict[int, list[IrToken]]
    types_by_name: dict[str, list[IrToken]]
    namespace_name: str | None = None
    semantic_version: str = ""

    def message(self, message_id: int) -> list[IrToken] | None:
        """Return token stream for a message id."""

        return self.messages_by_id.get(message_id)

    def messages(self) -> list[list[IrToken]]:
        """Return all message token streams."""

        return list(self.messages_by_id.values())

    def type_tokens(self, name: str) -> list[IrToken] | None:
        """Return token stream for a named type."""

        return self.types_by_name.get(name)

