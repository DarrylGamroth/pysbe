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
    type_name: str
    length: int = 1


@dataclass(frozen=True)
class EnumValueDef:
    """Enum valid value entry."""

    name: str
    value: int


@dataclass(frozen=True)
class SetChoiceDef:
    """Bitset choice entry."""

    name: str
    bit: int


@dataclass(frozen=True)
class TypeDef:
    """Parsed schema type definition."""

    name: str
    kind: str
    primitive_type: str | None = None
    length: int = 1
    since_version: int = 0
    presence: str = "required"
    null_value: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    const_value: str | None = None
    members: tuple[TypeRef, ...] = ()
    enum_values: tuple[EnumValueDef, ...] = ()
    set_choices: tuple[SetChoiceDef, ...] = ()


@dataclass(frozen=True)
class FieldDef:
    """Parsed field/group/data definition."""

    name: str
    id: int
    kind: str
    type_name: str | None = None
    since_version: int = 0
    presence: str | None = None
    null_value: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    const_value: str | None = None
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
    node: ET.Element,
    *,
    owner_type_name: str,
    types_by_name: dict[str, TypeDef],
    context: ValidationContext,
    path: str,
) -> tuple[TypeRef, ...]:
    members: list[TypeRef] = []
    names_seen: set[str] = set()
    for member in node:
        member_tag = _tag_name(member.tag)
        if member_tag in {"data", "group"}:
            context.error(f"{path} member kind {member_tag!r} is not valid within composite")
        if member_tag not in {"type", "enum", "set", "composite", "ref"}:
            continue

        member_name = _required_attrib(member, "name", context, path)
        context.validate_symbolic_name(member_name, "composite member")
        context.validate_identifier(member_name, "composite member")
        if member_name in names_seen:
            context.error(f"{path} contains duplicate member name {member_name!r}")
        names_seen.add(member_name)

        member_path = f"{path}.{member_name}"
        member_length = _int_attrib(member, "length", 1, context, member_path)
        if member_length <= 0:
            context.error(f"{member_path}.length must be >= 1")

        if member_tag == "ref":
            referenced_type = _required_attrib(member, "type", context, member_path)
            members.append(
                TypeRef(name=member_name, type_name=referenced_type, length=member_length)
            )
            continue

        synthetic_type_name = f"{owner_type_name}.{member_name}"
        if synthetic_type_name in types_by_name:
            context.error(
                f"{member_path} resolves to duplicate synthetic type {synthetic_type_name!r}"
            )

        if member_tag == "type":
            primitive_type = _required_attrib(member, "primitiveType", context, member_path)
            if primitive_type not in PRIMITIVE_TYPE_NAMES:
                context.error(f"{member_path} uses unknown primitiveType {primitive_type!r}")
            inline_length = _int_attrib(member, "length", 1, context, member_path)
            if inline_length <= 0:
                context.error(f"{member_path}.length must be >= 1")
            presence = member.attrib.get("presence", "required")
            if presence not in {"required", "optional", "constant"}:
                context.error(f"{member_path}.presence must be required/optional/constant")
            types_by_name[synthetic_type_name] = TypeDef(
                name=synthetic_type_name,
                kind="type",
                primitive_type=primitive_type,
                length=inline_length,
                since_version=_int_attrib(member, "sinceVersion", 0, context, member_path),
                presence=presence,
                null_value=member.attrib.get("nullValue"),
                min_value=member.attrib.get("minValue"),
                max_value=member.attrib.get("maxValue"),
                const_value=member.attrib.get("value"),
            )
            members.append(TypeRef(name=member_name, type_name=synthetic_type_name, length=1))
            continue

        if member_tag == "enum":
            encoding_type = _required_attrib(member, "encodingType", context, member_path)
            if encoding_type not in PRIMITIVE_TYPE_NAMES:
                context.error(f"{member_path} uses unknown encodingType {encoding_type!r}")
            types_by_name[synthetic_type_name] = TypeDef(
                name=synthetic_type_name,
                kind="enum",
                primitive_type=encoding_type,
                enum_values=_parse_enum_values(member, context, member_path),
                since_version=_int_attrib(member, "sinceVersion", 0, context, member_path),
            )
            members.append(
                TypeRef(name=member_name, type_name=synthetic_type_name, length=member_length)
            )
            continue

        if member_tag == "set":
            encoding_type = _required_attrib(member, "encodingType", context, member_path)
            if encoding_type not in PRIMITIVE_TYPE_NAMES:
                context.error(f"{member_path} uses unknown encodingType {encoding_type!r}")
            types_by_name[synthetic_type_name] = TypeDef(
                name=synthetic_type_name,
                kind="set",
                primitive_type=encoding_type,
                set_choices=_parse_set_choices(member, context, member_path),
                since_version=_int_attrib(member, "sinceVersion", 0, context, member_path),
            )
            members.append(
                TypeRef(name=member_name, type_name=synthetic_type_name, length=member_length)
            )
            continue

        # inline composite
        types_by_name[synthetic_type_name] = TypeDef(
            name=synthetic_type_name,
            kind="composite",
            members=_parse_composite_members(
                member,
                owner_type_name=synthetic_type_name,
                types_by_name=types_by_name,
                context=context,
                path=member_path,
            ),
            since_version=_int_attrib(member, "sinceVersion", 0, context, member_path),
        )
        members.append(
            TypeRef(name=member_name, type_name=synthetic_type_name, length=member_length)
        )
    return tuple(members)


def _parse_enum_values(
    node: ET.Element, context: ValidationContext, path: str
) -> tuple[EnumValueDef, ...]:
    values: list[EnumValueDef] = []
    names_seen: set[str] = set()
    numbers_seen: set[int] = set()
    for child in node:
        if _tag_name(child.tag) != "validValue":
            continue
        name = _required_attrib(child, "name", context, path)
        if name in names_seen:
            context.error(f"{path} contains duplicate enum validValue name {name!r}")
        names_seen.add(name)
        text = (child.text or "").strip()
        if text == "":
            context.error(f"{path}.validValue[{name}] must contain an integer value")
        try:
            value = int(text, 0)
        except ValueError as exc:
            context.error(f"{path}.validValue[{name}] must be integer, got {text!r}")
            raise RuntimeError("unreachable") from exc
        if value in numbers_seen:
            context.warning(f"{path} contains duplicate enum numeric value {value}")
        numbers_seen.add(value)
        values.append(EnumValueDef(name=name, value=value))
    return tuple(values)


def _parse_set_choices(
    node: ET.Element, context: ValidationContext, path: str
) -> tuple[SetChoiceDef, ...]:
    choices: list[SetChoiceDef] = []
    names_seen: set[str] = set()
    bits_seen: set[int] = set()
    for child in node:
        if _tag_name(child.tag) != "choice":
            continue
        name = _required_attrib(child, "name", context, path)
        if name in names_seen:
            context.error(f"{path} contains duplicate set choice name {name!r}")
        names_seen.add(name)
        text = (child.text or "").strip()
        if text == "":
            context.error(f"{path}.choice[{name}] must contain an integer bit position")
        try:
            bit = int(text, 0)
        except ValueError as exc:
            context.error(f"{path}.choice[{name}] must be integer, got {text!r}")
            raise RuntimeError("unreachable") from exc
        if bit in bits_seen:
            context.warning(f"{path} contains duplicate set bit position {bit}")
        bits_seen.add(bit)
        choices.append(SetChoiceDef(name=name, bit=bit))
    return tuple(choices)


def _parse_type_node(
    type_node: ET.Element,
    *,
    type_name: str,
    types_by_name: dict[str, TypeDef],
    context: ValidationContext,
    path: str,
) -> TypeDef:
    type_tag = _tag_name(type_node.tag)

    if type_tag == "type":
        primitive_type = _required_attrib(type_node, "primitiveType", context, path)
        length = _int_attrib(type_node, "length", 1, context, path)
        since_version = _int_attrib(type_node, "sinceVersion", 0, context, path)
        presence = type_node.attrib.get("presence", "required")
        if presence not in {"required", "optional", "constant"}:
            context.error(f"{path}.presence must be required/optional/constant")
        if primitive_type not in PRIMITIVE_TYPE_NAMES:
            context.error(f"{path} uses unknown primitiveType {primitive_type!r}")
        if length <= 0:
            context.error(f"{path}.length must be >= 1")
        return TypeDef(
            name=type_name,
            kind=type_tag,
            primitive_type=primitive_type,
            length=length,
            since_version=since_version,
            presence=presence,
            null_value=type_node.attrib.get("nullValue"),
            min_value=type_node.attrib.get("minValue"),
            max_value=type_node.attrib.get("maxValue"),
            const_value=type_node.attrib.get("value"),
        )

    if type_tag == "composite":
        members = _parse_composite_members(
            type_node,
            owner_type_name=type_name,
            types_by_name=types_by_name,
            context=context,
            path=path,
        )
        return TypeDef(
            name=type_name,
            kind=type_tag,
            members=members,
            since_version=_int_attrib(type_node, "sinceVersion", 0, context, path),
        )

    if type_tag == "enum":
        encoding_type = _required_attrib(type_node, "encodingType", context, path)
        if encoding_type not in PRIMITIVE_TYPE_NAMES:
            context.error(f"{path} uses unknown encodingType {encoding_type!r}")
        values = _parse_enum_values(type_node, context, path)
        return TypeDef(
            name=type_name,
            kind=type_tag,
            primitive_type=encoding_type,
            enum_values=values,
            since_version=_int_attrib(type_node, "sinceVersion", 0, context, path),
        )

    if type_tag == "set":
        encoding_type = _required_attrib(type_node, "encodingType", context, path)
        if encoding_type not in PRIMITIVE_TYPE_NAMES:
            context.error(f"{path} uses unknown encodingType {encoding_type!r}")
        choices = _parse_set_choices(type_node, context, path)
        return TypeDef(
            name=type_name,
            kind=type_tag,
            primitive_type=encoding_type,
            set_choices=choices,
            since_version=_int_attrib(type_node, "sinceVersion", 0, context, path),
        )

    raise ValueError(f"unsupported type tag: {type_tag!r}")


def _parse_types(root: ET.Element, context: ValidationContext) -> dict[str, TypeDef]:
    types_by_name: dict[str, TypeDef] = {
        primitive: TypeDef(name=primitive, kind="primitive", primitive_type=primitive, length=1)
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
            context.validate_symbolic_name(type_name, "type")
            context.validate_identifier(type_name, "type")
            if type_name in types_by_name:
                context.error(f"types contains duplicate type name {type_name!r}")
            type_def = _parse_type_node(
                type_node,
                type_name=type_name,
                types_by_name=types_by_name,
                context=context,
                path=f"types.{type_name}",
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
        context.validate_symbolic_name(name, "field")
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
                    since_version=_int_attrib(node, "sinceVersion", 0, context, field_path),
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

        fields.append(
            FieldDef(
                name=name,
                id=field_id,
                kind=kind,
                type_name=type_name,
                since_version=_int_attrib(node, "sinceVersion", 0, context, field_path),
                presence=node.attrib.get("presence"),
                null_value=node.attrib.get("nullValue"),
                min_value=node.attrib.get("minValue"),
                max_value=node.attrib.get("maxValue"),
                const_value=node.attrib.get("value"),
            )
        )

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
        context.validate_symbolic_name(name, "message")
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
            strict_names=validate,
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
