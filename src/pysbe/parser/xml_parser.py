"""Schema XML parser and Phase 1 validation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from pysbe.parser.validation import ValidationContext, ValidationOptions

PRIMITIVE_TYPE_NAMES = {
    "char",
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "float",
    "double",
}

BYTE_ORDERS = {"littleEndian", "bigEndian"}


def _tag_name(tag: str) -> str:
    return tag.split("}")[-1]


def _required_attrib(node: ET.Element, name: str, context: ValidationContext, path: str) -> str:
    value = node.attrib.get(name)
    if value is None or value == "":
        context.error(f"{path} missing required attribute {name!r}")
    assert value is not None
    return value


def _int_attrib(
    node: ET.Element,
    name: str,
    default: int,
    context: ValidationContext,
    path: str,
) -> int:
    value = node.attrib.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        context.error(f"{path}.{name} must be an integer, got {value!r}")
        raise RuntimeError("unreachable") from exc


@dataclass(frozen=True)
class TypeRef:
    """Reference to a type used by a field or composite member."""

    name: str


@dataclass(frozen=True)
class TypeDef:
    """Parsed schema type definition."""

    name: str
    kind: str
    primitive_type: str | None = None
    members: tuple[TypeRef, ...] = ()


@dataclass(frozen=True)
class FieldDef:
    """Parsed field/group/data definition."""

    name: str
    id: int
    kind: str
    type_name: str | None = None
    children: tuple[FieldDef, ...] = ()


@dataclass(frozen=True)
class MessageDef:
    """Parsed message definition."""

    name: str
    id: int
    block_length: int
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class SchemaDef:
    """Parsed schema model used by subsequent IR/codegen phases."""

    package_name: str
    id: int
    version: int
    byte_order: str
    header_type: str
    types_by_name: dict[str, TypeDef] = field(default_factory=dict)
    messages: tuple[MessageDef, ...] = ()
    warnings: tuple[str, ...] = ()


def _parse_composite_members(
    node: ET.Element, context: ValidationContext, path: str
) -> tuple[TypeRef, ...]:
    members: list[TypeRef] = []
    names_seen: set[str] = set()
    for member in node:
        member_tag = _tag_name(member.tag)
        if member_tag not in {"type", "enum", "set", "composite", "ref"}:
            continue

        member_name = _required_attrib(member, "name", context, path)
        if member_name in names_seen:
            context.error(f"{path} contains duplicate member name {member_name!r}")
        names_seen.add(member_name)

        type_name = member.attrib.get("type")
        if member_tag == "type":
            type_name = member.attrib.get("primitiveType")
        if member_tag == "ref":
            type_name = member.attrib.get("type")
        if type_name is None:
            # In-schema nested type declarations can omit `type`; only keep refs we can resolve.
            continue
        members.append(TypeRef(name=type_name))
    return tuple(members)


def _parse_types(root: ET.Element, context: ValidationContext) -> dict[str, TypeDef]:
    types_by_name: dict[str, TypeDef] = {
        primitive: TypeDef(name=primitive, kind="primitive", primitive_type=primitive)
        for primitive in sorted(PRIMITIVE_TYPE_NAMES)
    }
    for types_node in root:
        if _tag_name(types_node.tag) != "types":
            continue
        for type_node in types_node:
            type_tag = _tag_name(type_node.tag)
            if type_tag not in {"type", "enum", "set", "composite"}:
                continue

            type_name = _required_attrib(type_node, "name", context, "types")
            context.validate_identifier(type_name, "type")
            if type_name in types_by_name:
                context.error(f"types contains duplicate type name {type_name!r}")

            if type_tag == "type":
                primitive_type = _required_attrib(
                    type_node, "primitiveType", context, f"types.{type_name}"
                )
                if primitive_type not in PRIMITIVE_TYPE_NAMES:
                    context.error(
                        f"types.{type_name} uses unknown primitiveType {primitive_type!r}"
                    )
                type_def = TypeDef(
                    name=type_name, kind=type_tag, primitive_type=primitive_type
                )
            elif type_tag == "composite":
                members = _parse_composite_members(type_node, context, f"types.{type_name}")
                type_def = TypeDef(name=type_name, kind=type_tag, members=members)
            else:
                encoding_type = _required_attrib(
                    type_node, "encodingType", context, f"types.{type_name}"
                )
                if encoding_type not in PRIMITIVE_TYPE_NAMES:
                    context.error(
                        f"types.{type_name} uses unknown encodingType {encoding_type!r}"
                    )
                type_def = TypeDef(
                    name=type_name, kind=type_tag, primitive_type=encoding_type
                )
            types_by_name[type_name] = type_def
    return types_by_name


def _phase_for_field_kind(kind: str) -> int:
    if kind == "field":
        return 0
    if kind == "group":
        return 1
    if kind == "data":
        return 2
    raise ValueError(f"unsupported field kind: {kind}")


def _parse_fields(
    nodes: list[ET.Element],
    *,
    types_by_name: dict[str, TypeDef],
    context: ValidationContext,
    path: str,
) -> tuple[FieldDef, ...]:
    fields: list[FieldDef] = []
    names_seen: set[str] = set()
    ids_seen: set[int] = set()
    current_phase = 0

    for node in nodes:
        kind = _tag_name(node.tag)
        if kind not in {"field", "group", "data"}:
            continue
        phase = _phase_for_field_kind(kind)
        if phase < current_phase:
            context.error(f"{path} violates field/group/data ordering at {kind!r}")
        current_phase = phase

        name = _required_attrib(node, "name", context, path)
        context.validate_identifier(name, "field")
        field_path = f"{path}.{name}"

        field_id = _int_attrib(node, "id", -1, context, field_path)
        if field_id < 0:
            context.error(f"{field_path} requires non-negative id")

        if name in names_seen:
            context.error(f"{path} contains duplicate field name {name!r}")
        names_seen.add(name)
        if field_id in ids_seen:
            context.error(f"{path} contains duplicate field id {field_id}")
        ids_seen.add(field_id)

        if kind == "group":
            dimension_type = node.attrib.get("dimensionType", "groupSizeEncoding")
            dimension_def = types_by_name.get(dimension_type)
            if dimension_def is None:
                context.error(
                    f"{field_path} dimensionType {dimension_type!r} does not exist in types"
                )
            elif dimension_def.kind != "composite":
                context.error(
                    f"{field_path} dimensionType {dimension_type!r} must reference a composite"
                )
            children = _parse_fields(
                list(node),
                types_by_name=types_by_name,
                context=context,
                path=field_path,
            )
            fields.append(
                FieldDef(
                    name=name,
                    id=field_id,
                    kind=kind,
                    type_name=dimension_type,
                    children=children,
                )
            )
            continue

        type_name = _required_attrib(node, "type", context, field_path)
        type_def = types_by_name.get(type_name)
        if type_def is None:
            context.error(f"{field_path} references unknown type {type_name!r}")
        if kind == "data" and type_def is not None and type_def.kind != "composite":
            context.error(f"{field_path} data field type must reference a composite")

        fields.append(FieldDef(name=name, id=field_id, kind=kind, type_name=type_name))

    return tuple(fields)


def _parse_messages(
    root: ET.Element,
    *,
    types_by_name: dict[str, TypeDef],
    context: ValidationContext,
) -> tuple[MessageDef, ...]:
    messages: list[MessageDef] = []
    ids_seen: set[int] = set()
    names_seen: set[str] = set()
    for node in root:
        if _tag_name(node.tag) != "message":
            continue
        name = _required_attrib(node, "name", context, "message")
        context.validate_identifier(name, "message")
        message_path = f"message.{name}"
        message_id = _int_attrib(node, "id", -1, context, message_path)
        if message_id < 0:
            context.error(f"{message_path} requires non-negative id")
        if name in names_seen:
            context.error(f"schema contains duplicate message name {name!r}")
        names_seen.add(name)
        if message_id in ids_seen:
            context.error(f"schema contains duplicate message id {message_id}")
        ids_seen.add(message_id)

        block_length = _int_attrib(node, "blockLength", 0, context, message_path)
        if block_length < 0:
            context.error(f"{message_path}.blockLength must be >= 0")

        fields = _parse_fields(
            list(node),
            types_by_name=types_by_name,
            context=context,
            path=message_path,
        )
        messages.append(
            MessageDef(name=name, id=message_id, block_length=block_length, fields=fields)
        )

    if not messages:
        context.warning("schema contains no messages")
    return tuple(messages)


def parse_schema(
    path: str | Path,
    *,
    validate: bool = True,
    warnings_fatal: bool = False,
    suppress_warnings: bool = False,
) -> SchemaDef:
    """Parse an XML schema file into an internal schema model."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Schema file not found: {source}")

    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in schema {source}: {exc}") from exc

    if _tag_name(root.tag) != "messageSchema":
        raise ValueError(f"Expected messageSchema root element, got {root.tag!r}")

    context = ValidationContext(
        ValidationOptions(
            warnings_fatal=warnings_fatal,
            suppress_warnings=suppress_warnings,
        )
    )

    package_name = root.attrib.get("package", "")
    schema_id = _int_attrib(root, "id", -1, context, "messageSchema")
    if schema_id < 0:
        context.error("messageSchema requires non-negative id")
    version = _int_attrib(root, "version", 0, context, "messageSchema")
    if version < 0:
        context.error("messageSchema.version must be >= 0")

    byte_order = root.attrib.get("byteOrder", "littleEndian")
    if validate and byte_order not in BYTE_ORDERS:
        context.error(f"messageSchema.byteOrder must be one of {sorted(BYTE_ORDERS)}")

    types_by_name = _parse_types(root, context)
    header_type = root.attrib.get("headerType", "messageHeader")
    header_def = types_by_name.get(header_type)
    if validate and header_def is None:
        context.error(f"messageSchema.headerType {header_type!r} is not defined in <types>")
    if validate and header_def is not None and header_def.kind != "composite":
        context.error("messageSchema.headerType must reference a composite type")

    messages = _parse_messages(root, types_by_name=types_by_name, context=context)

    return SchemaDef(
        package_name=package_name,
        id=schema_id,
        version=version,
        byte_order=byte_order,
        header_type=header_type,
        types_by_name=types_by_name,
        messages=messages,
        warnings=tuple(context.warnings),
    )
