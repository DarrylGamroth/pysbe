"""Parser package exports."""

from pysbe.parser.validation import ValidationError
from pysbe.parser.xml_parser import (
    EnumValueDef,
    FieldDef,
    MessageDef,
    SchemaDef,
    SetChoiceDef,
    TypeDef,
    TypeRef,
    parse_schema,
)

__all__ = [
    "EnumValueDef",
    "FieldDef",
    "MessageDef",
    "SchemaDef",
    "SetChoiceDef",
    "TypeDef",
    "TypeRef",
    "ValidationError",
    "parse_schema",
]
