"""Generate Python codec source from parsed schema."""

from __future__ import annotations

from dataclasses import dataclass

from pysbe.codegen.naming import class_name, sanitize_identifier
from pysbe.parser import FieldDef, MessageDef, SchemaDef, TypeDef

PRIMITIVE_SIZE: dict[str, int] = {
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


@dataclass(frozen=True)
class ResolvedType:
    """Resolved type metadata for code generation."""

    kind: str
    name: str
    primitive_type: str | None
    length: int
    encoded_length: int


def _resolve_type(schema: SchemaDef, type_name: str) -> ResolvedType:
    type_def = schema.types_by_name.get(type_name)
    if type_def is None:
        raise ValueError(f"unknown type {type_name!r}")

    if type_def.kind in {"primitive", "type"}:
        if type_def.primitive_type is None:
            raise ValueError(f"type {type_name!r} missing primitive type")
        primitive_size = PRIMITIVE_SIZE[type_def.primitive_type]
        encoded_length = primitive_size * type_def.length
        return ResolvedType(
            kind="primitive",
            name=type_name,
            primitive_type=type_def.primitive_type,
            length=type_def.length,
            encoded_length=encoded_length,
        )

    if type_def.kind in {"enum", "set"}:
        if type_def.primitive_type is None:
            raise ValueError(f"type {type_name!r} missing encoding primitive type")
        encoded_length = PRIMITIVE_SIZE[type_def.primitive_type]
        return ResolvedType(
            kind=type_def.kind,
            name=type_name,
            primitive_type=type_def.primitive_type,
            length=1,
            encoded_length=encoded_length,
        )

    if type_def.kind != "composite":
        raise ValueError(f"unsupported type kind {type_def.kind!r}")

    length = 0
    for member in type_def.members:
        member_type = _resolve_type(schema, member.type_name)
        length += member_type.encoded_length * member.length
    return ResolvedType(
        kind="composite",
        name=type_name,
        primitive_type=None,
        length=1,
        encoded_length=length,
    )


def _composite_member_layout(
    schema: SchemaDef, type_def: TypeDef
) -> list[tuple[str, str, int, int]]:
    layout: list[tuple[str, str, int, int]] = []
    offset = 0
    for member in type_def.members:
        member_resolved = _resolve_type(schema, member.type_name)
        member_len = member_resolved.encoded_length * member.length
        layout.append((member.name, member.type_name, member.length, offset))
        offset += member_len
    return layout


def _method_name(name: str) -> str:
    return sanitize_identifier(name)


def _emit_enum_and_set_types(schema: SchemaDef) -> str:
    lines: list[str] = []
    for type_def in sorted(schema.types_by_name.values(), key=lambda item: item.name):
        type_class = class_name(type_def.name)
        if type_def.kind == "enum":
            lines.append(f"class {type_class}:")
            if not type_def.enum_values:
                lines.append("    pass")
            for value in type_def.enum_values:
                lines.append(f"    {sanitize_identifier(value.name).upper()} = {value.value}")
            lines.append("")
        elif type_def.kind == "set":
            lines.append(f"class {type_class}:")
            if not type_def.set_choices:
                lines.append("    pass")
            for choice in type_def.set_choices:
                lines.append(f"    {sanitize_identifier(choice.name).upper()} = 1 << {choice.bit}")
            lines.append("")
    return "\n".join(lines)


def _emit_composite_codec(schema: SchemaDef, type_def: TypeDef, *, encoder: bool) -> str:
    suffix = "Encoder" if encoder else "Decoder"
    class_label = f"{class_name(type_def.name)}{suffix}"
    lines = [f"class {class_label}:", "    def __init__(self, buffer, offset=0):"]
    writable = "True" if encoder else "False"
    lines.append(f"        self.buffer = to_memoryview(buffer, writable={writable})")
    lines.append("        self.offset = offset")
    lines.append("")
    lines.append("    @classmethod")
    lines.append("    def wrap(cls, buffer, offset=0):")
    lines.append("        return cls(buffer, offset)")
    lines.append("")

    for member_name, member_type_name, member_length, member_offset in _composite_member_layout(
        schema, type_def
    ):
        method = _method_name(member_name)
        resolved = _resolve_type(schema, member_type_name)
        if resolved.kind == "primitive" and member_length == 1 and resolved.length == 1:
            lines.append(f"    def {method}(self):")
            lines.append(
                "        return read_primitive("
                f"self.buffer, self.offset + {member_offset}, {resolved.primitive_type!r}, "
                "byte_order=BYTE_ORDER)"
            )
            lines.append("")
            if encoder:
                lines.append(f"    def {method}_set(self, value):")
                lines.append(
                    "        write_primitive("
                    f"self.buffer, self.offset + {member_offset}, {resolved.primitive_type!r}, "
                    "value, byte_order=BYTE_ORDER)"
                )
                lines.append("")
            continue

        if resolved.kind == "primitive":
            total_length = member_length * resolved.length
            lines.append(f"    def {method}(self):")
            lines.append(
                "        return view_primitive_array("
                f"self.buffer, self.offset + {member_offset}, {resolved.primitive_type!r}, "
                f"{total_length}, byte_order=BYTE_ORDER, writable={str(encoder)})"
            )
            lines.append("")
            if encoder:
                lines.append(f"    def {method}_set(self, values):")
                lines.append(f"        target = self.{method}()")
                lines.append("        np.copyto(target, np.asarray(values, dtype=target.dtype))")
                lines.append("")
            continue

        nested_encoder = f"{class_name(member_type_name)}{suffix}"
        lines.append(f"    def {method}(self):")
        lines.append(f"        return {nested_encoder}(self.buffer, self.offset + {member_offset})")
        lines.append("")

    return "\n".join(lines)


def _message_block_length(schema: SchemaDef, message: MessageDef) -> int:
    if message.block_length > 0:
        return message.block_length
    length = 0
    for field in message.fields:
        if field.kind != "field":
            break
        if field.type_name is None:
            continue
        resolved = _resolve_type(schema, field.type_name)
        length += resolved.encoded_length
    return length


def _field_layout(schema: SchemaDef, message: MessageDef) -> list[tuple[FieldDef, int]]:
    layout: list[tuple[FieldDef, int]] = []
    offset = 0
    for field in message.fields:
        if field.kind != "field":
            raise NotImplementedError(
                "Phase 4 codegen supports only fixed `field` entries (no group/data yet)"
            )
        if field.type_name is None:
            raise ValueError(f"message field {field.name!r} is missing type")
        layout.append((field, offset))
        offset += _resolve_type(schema, field.type_name).encoded_length
    return layout


def _emit_message_codec(
    schema: SchemaDef,
    message: MessageDef,
    *,
    encoder: bool,
    header_size: int,
) -> str:
    suffix = "Encoder" if encoder else "Decoder"
    class_label = f"{class_name(message.name)}{suffix}"
    lines = [f"class {class_label}:"]
    lines.append(f"    TEMPLATE_ID = {message.id}")
    lines.append(f"    SCHEMA_ID = {schema.id}")
    lines.append(f"    SCHEMA_VERSION = {schema.version}")
    lines.append(f"    BLOCK_LENGTH = {_message_block_length(schema, message)}")
    lines.append("")
    lines.append("    def __init__(self, buffer, offset=0):")
    writable = "True" if encoder else "False"
    lines.append(f"        self.buffer = to_memoryview(buffer, writable={writable})")
    lines.append("        self.offset = offset")
    lines.append("")

    if encoder:
        lines.append("    @classmethod")
        lines.append("    def wrap_and_apply_header(cls, buffer, offset=0):")
        lines.append("        header = MessageHeaderEncoder(buffer, offset)")
        lines.append("        if hasattr(header, 'blockLength_set'):")
        lines.append("            header.blockLength_set(cls.BLOCK_LENGTH)")
        lines.append("        if hasattr(header, 'templateId_set'):")
        lines.append("            header.templateId_set(cls.TEMPLATE_ID)")
        lines.append("        if hasattr(header, 'schemaId_set'):")
        lines.append("            header.schemaId_set(cls.SCHEMA_ID)")
        lines.append("        if hasattr(header, 'version_set'):")
        lines.append("            header.version_set(cls.SCHEMA_VERSION)")
        lines.append(f"        return cls(buffer, offset + {header_size})")
        lines.append("")
    else:
        lines.append("    @classmethod")
        lines.append("    def wrap(cls, buffer, offset=0, *, with_header=True):")
        lines.append(f"        base = offset + {header_size} if with_header else offset")
        lines.append("        return cls(buffer, base)")
        lines.append("")

    for field, offset in _field_layout(schema, message):
        method = _method_name(field.name)
        assert field.type_name is not None
        resolved = _resolve_type(schema, field.type_name)
        if resolved.kind in {"primitive", "enum", "set"} and resolved.length == 1:
            lines.append(f"    def {method}(self):")
            lines.append(
                "        return read_primitive("
                f"self.buffer, self.offset + {offset}, {resolved.primitive_type!r}, "
                "byte_order=BYTE_ORDER)"
            )
            lines.append("")
            if encoder:
                lines.append(f"    def {method}_set(self, value):")
                lines.append(
                    "        write_primitive("
                    f"self.buffer, self.offset + {offset}, {resolved.primitive_type!r}, "
                    "value, byte_order=BYTE_ORDER)"
                )
                lines.append("")
            if resolved.kind == "set":
                lines.append(f"    def {method}_has(self, flag):")
                lines.append(f"        return bool(self.{method}() & flag)")
                lines.append("")
            continue

        if resolved.kind == "primitive":
            lines.append(f"    def {method}(self):")
            lines.append(
                "        return view_primitive_array("
                f"self.buffer, self.offset + {offset}, {resolved.primitive_type!r}, "
                f"{resolved.length}, byte_order=BYTE_ORDER, writable={str(encoder)})"
            )
            lines.append("")
            if encoder:
                lines.append(f"    def {method}_set(self, values):")
                lines.append(f"        target = self.{method}()")
                lines.append("        np.copyto(target, np.asarray(values, dtype=target.dtype))")
                lines.append("")
                if resolved.primitive_type == "char":
                    lines.append(f"    def {method}_set_str(self, text):")
                    lines.append("        encoded = text.encode('ascii', errors='ignore')")
                    lines.append(f"        trimmed = encoded[:{resolved.length}]")
                    lines.append(
                        f"        pad_len = len(self.{method}()) - len(trimmed)"
                    )
                    lines.append(
                        "        padded = trimmed + b'\\x00' * pad_len"
                    )
                    lines.append(
                        f"        self.{method}_set(np.frombuffer(padded, dtype=np.uint8))"
                    )
                    lines.append("")
            if resolved.primitive_type == "char":
                lines.append(f"    def {method}_as_str(self):")
                lines.append(
                    f"        return bytes(self.{method}()).decode('ascii', "
                    "errors='ignore').rstrip('\\x00')"
                )
                lines.append("")
            continue

        if resolved.kind == "composite":
            nested_class = f"{class_name(field.type_name)}{suffix}"
            lines.append(f"    def {method}(self):")
            lines.append(f"        return {nested_class}(self.buffer, self.offset + {offset})")
            lines.append("")
            continue

        raise ValueError(f"unsupported field type kind: {resolved.kind!r}")

    return "\n".join(lines)


def emit_module(schema: SchemaDef, module_name: str) -> str:
    """Emit generated Python module text for a parsed schema."""

    header_type = schema.types_by_name[schema.header_type]
    header_length = _resolve_type(schema, schema.header_type).encoded_length

    parts = [
        '"""Generated by pysbe codegen (Phase 4)."""',
        "",
        "from __future__ import annotations",
        "",
        "import numpy as np",
        "",
        "from pysbe.runtime import (",
        "    read_primitive,",
        "    to_memoryview,",
        "    view_primitive_array,",
        "    write_primitive,",
        ")",
        "",
        f"BYTE_ORDER = {schema.byte_order!r}",
        f"SCHEMA_ID = {schema.id}",
        f"SCHEMA_VERSION = {schema.version}",
        f"HEADER_SIZE = {header_length}",
        "",
        _emit_enum_and_set_types(schema).rstrip(),
    ]

    # Composite codecs (header first for stable naming).
    composite_types = [
        type_def
        for type_def in schema.types_by_name.values()
        if type_def.kind == "composite" and type_def.name != schema.header_type
    ]
    parts.append(_emit_composite_codec(schema, header_type, encoder=True))
    parts.append("")
    parts.append(_emit_composite_codec(schema, header_type, encoder=False))
    parts.append("")
    for composite in sorted(composite_types, key=lambda item: item.name):
        parts.append(_emit_composite_codec(schema, composite, encoder=True))
        parts.append("")
        parts.append(_emit_composite_codec(schema, composite, encoder=False))
        parts.append("")

    for message in schema.messages:
        parts.append(_emit_message_codec(schema, message, encoder=True, header_size=header_length))
        parts.append("")
        parts.append(_emit_message_codec(schema, message, encoder=False, header_size=header_length))
        parts.append("")

    cleaned = "\n".join(section for section in parts if section is not None).rstrip() + "\n"
    # Wrap in module namespace for include/import parity with requested module name.
    return (
        f"# module: {module_name}\n"
        f"# package: {schema.package_name}\n"
        f"{cleaned}"
    )
