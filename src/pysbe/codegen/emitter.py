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

PRIMITIVE_NULL_VALUE: dict[str, str] = {
    "char": "0",
    "int8": "-128",
    "uint8": "255",
    "int16": "-32768",
    "uint16": "65535",
    "int32": "-2147483648",
    "uint32": "4294967295",
    "float": "float('nan')",
    "int64": "-9223372036854775808",
    "uint64": "18446744073709551615",
    "double": "float('nan')",
}

NUMPY_DTYPE_LITERAL: dict[str, str] = {
    "char": "np.uint8",
    "int8": "np.int8",
    "uint8": "np.uint8",
    "int16": "np.int16",
    "uint16": "np.uint16",
    "int32": "np.int32",
    "uint32": "np.uint32",
    "float": "np.float32",
    "int64": "np.int64",
    "uint64": "np.uint64",
    "double": "np.float64",
}

@dataclass(frozen=True)
class ResolvedType:
    """Resolved type metadata for code generation."""

    kind: str
    name: str
    primitive_type: str | None
    length: int
    encoded_length: int


@dataclass(frozen=True)
class FieldMeta:
    """Merged metadata from field + referenced type."""

    since_version: int
    presence: str
    const_value: str | None
    null_value: str | None
    min_value: str | None
    max_value: str | None


@dataclass(frozen=True)
class ContainerLayout:
    """Fixed field layout information for a message/group."""

    fixed_fields: list[tuple[FieldDef, int]]
    block_length: int


def _method_name(name: str) -> str:
    return sanitize_identifier(name)


def _default_null_literal(primitive_type: str) -> str:
    return PRIMITIVE_NULL_VALUE[primitive_type]


def _not_present_literal(meta: FieldMeta, primitive_type: str) -> str:
    explicit_null = _python_value_literal(meta.null_value, primitive_type)
    if explicit_null is not None:
        return explicit_null
    return _default_null_literal(primitive_type)


def _field_accessor_method_names(schema: SchemaDef, field: FieldDef, *, encoder: bool) -> list[str]:
    method = _method_name(field.name)
    if field.kind == "group":
        return [f"{method}_begin" if encoder else method]
    if field.kind == "data":
        if encoder:
            return [f"{method}_set"]
        return [method, f"{method}_as_str"]

    if field.type_name is None:
        raise ValueError(f"field {field.name!r} missing type")
    resolved = _resolve_type(schema, field.type_name)
    if resolved.kind in {"primitive", "enum", "set"} and resolved.length == 1:
        names = [method]
        if encoder:
            names.append(f"{method}_set")
        if resolved.kind == "set":
            names.append(f"{method}_has")
        if field.type_name in schema.types_by_name:
            type_def = schema.types_by_name[field.type_name]
            meta = _field_meta(schema, field, type_def)
            if resolved.primitive_type is not None and meta.presence == "optional":
                names.append(f"{method}_is_null")
                names.append(f"{method}_or_none")
        return names
    if resolved.kind == "primitive":
        names = [method]
        if encoder:
            names.append(f"{method}_set")
            if resolved.primitive_type == "char":
                names.append(f"{method}_set_str")
        if resolved.primitive_type == "char":
            names.append(f"{method}_as_str")
        return names
    if resolved.kind == "composite":
        return [method]
    raise ValueError(f"unsupported field type kind: {resolved.kind!r}")


def _assert_no_method_collisions(
    methods: list[str],
    *,
    class_label: str,
    reserved: set[str],
) -> None:
    seen: set[str] = set(reserved)
    for method in methods:
        if method in seen:
            raise ValueError(
                f"{class_label} contains duplicate generated method name {method!r}. "
                "Rename schema fields to avoid sanitized-name collisions."
            )
        seen.add(method)


def _resolve_type(schema: SchemaDef, type_name: str) -> ResolvedType:
    type_def = schema.types_by_name.get(type_name)
    if type_def is None:
        raise ValueError(f"unknown type {type_name!r}")
    if type_def.kind in {"primitive", "type"}:
        if type_def.primitive_type is None:
            raise ValueError(f"type {type_name!r} missing primitive type")
        size = PRIMITIVE_SIZE[type_def.primitive_type] * type_def.length
        return ResolvedType(
            kind="primitive",
            name=type_name,
            primitive_type=type_def.primitive_type,
            length=type_def.length,
            encoded_length=size,
        )
    if type_def.kind in {"enum", "set"}:
        if type_def.primitive_type is None:
            raise ValueError(f"type {type_name!r} missing primitive type")
        return ResolvedType(
            kind=type_def.kind,
            name=type_name,
            primitive_type=type_def.primitive_type,
            length=1,
            encoded_length=PRIMITIVE_SIZE[type_def.primitive_type],
        )
    if type_def.kind != "composite":
        raise ValueError(f"unsupported type kind {type_def.kind!r}")
    size = 0
    for member in type_def.members:
        member_type = _resolve_type(schema, member.type_name)
        size += member_type.encoded_length * member.length
    return ResolvedType(
        kind="composite",
        name=type_name,
        primitive_type=None,
        length=1,
        encoded_length=size,
    )


def _field_meta(schema: SchemaDef, field: FieldDef, type_def: TypeDef) -> FieldMeta:
    return FieldMeta(
        since_version=max(field.since_version, type_def.since_version),
        presence=field.presence or type_def.presence,
        const_value=field.const_value or type_def.const_value,
        null_value=field.null_value or type_def.null_value,
        min_value=field.min_value or type_def.min_value,
        max_value=field.max_value or type_def.max_value,
    )


def _python_value_literal(value: str | None, primitive_type: str | None) -> str | None:
    if value is None:
        return None
    if primitive_type in {"float", "double"}:
        return repr(float(value))
    if primitive_type == "char":
        if value.startswith("0x") or value.lstrip("-").isdigit():
            return str(int(value, 0))
        if len(value) == 1:
            return str(ord(value))
        return str(ord(value[0]))
    if primitive_type is None:
        return repr(value)
    return str(int(value, 0))


def _container_layout(schema: SchemaDef, fields: tuple[FieldDef, ...]) -> ContainerLayout:
    fixed_fields: list[tuple[FieldDef, int]] = []
    offset = 0
    for field in fields:
        if field.kind != "field":
            break
        if field.type_name is None:
            raise ValueError(f"field {field.name!r} missing type")
        fixed_fields.append((field, offset))
        offset += _resolve_type(schema, field.type_name).encoded_length
    return ContainerLayout(fixed_fields=fixed_fields, block_length=offset)


def _composite_member_layout(
    schema: SchemaDef,
    type_def: TypeDef,
) -> list[tuple[str, str, int, int]]:
    layout: list[tuple[str, str, int, int]] = []
    offset = 0
    for member in type_def.members:
        resolved = _resolve_type(schema, member.type_name)
        size = resolved.encoded_length * member.length
        layout.append((member.name, member.type_name, member.length, offset))
        offset += size
    return layout


def _dimension_spec(schema: SchemaDef, type_name: str) -> tuple[str, str, int, int]:
    type_def = schema.types_by_name[type_name]
    if type_def.kind != "composite" or len(type_def.members) < 2:
        raise ValueError(f"dimension type {type_name!r} must be composite with 2 members")
    first = _resolve_type(schema, type_def.members[0].type_name)
    second = _resolve_type(schema, type_def.members[1].type_name)
    if first.primitive_type is None or second.primitive_type is None:
        raise ValueError("dimension members must resolve to primitive types")
    first_size = first.encoded_length * type_def.members[0].length
    second_size = second.encoded_length * type_def.members[1].length
    return first.primitive_type, second.primitive_type, first_size, first_size + second_size


def _var_data_length_type(schema: SchemaDef, type_name: str) -> str:
    type_def = schema.types_by_name[type_name]
    if type_def.kind != "composite" or len(type_def.members) < 2:
        raise ValueError(f"var-data type {type_name!r} must be a composite")
    length_member = _resolve_type(schema, type_def.members[0].type_name)
    if length_member.primitive_type is None:
        raise ValueError(f"var-data type {type_name!r} length member must be primitive")
    return length_member.primitive_type


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


def _emit_scalar_accessor(
    lines: list[str],
    *,
    method: str,
    offset_expr: str,
    primitive_type: str,
    meta: FieldMeta,
    encoder: bool,
) -> None:
    const_literal = _python_value_literal(meta.const_value, primitive_type)
    min_literal = _python_value_literal(meta.min_value, primitive_type)
    max_literal = _python_value_literal(meta.max_value, primitive_type)
    null_literal = _not_present_literal(meta, primitive_type)

    lines.append(f"    def {method}(self):")
    if meta.since_version > 0:
        lines.append(f"        if self.acting_version < {meta.since_version}:")
        lines.append(f"            return {null_literal}")
    if meta.presence == "constant" and const_literal is not None:
        lines.append(f"        return {const_literal}")
    else:
        lines.append(
            "        return read_primitive("
            f"self.buffer, {offset_expr}, {primitive_type!r}, byte_order=BYTE_ORDER)"
        )
    lines.append("")

    if meta.presence == "optional":
        lines.append(f"    def {method}_is_null(self):")
        lines.append(f"        value = self.{method}()")
        if primitive_type in {"float", "double"}:
            lines.append("        return np.isnan(value)")
        else:
            lines.append(f"        return value == {null_literal}")
        lines.append("")
        lines.append(f"    def {method}_or_none(self):")
        lines.append(f"        value = self.{method}()")
        lines.append(f"        return None if self.{method}_is_null() else value")
        lines.append("")

    if not encoder:
        return

    lines.append(f"    def {method}_set(self, value):")
    if meta.since_version > 0:
        lines.append(f"        if self.acting_version < {meta.since_version}:")
        lines.append("            raise ValueError('field not present in acting version')")
    if meta.presence == "constant":
        lines.append("        raise ValueError('cannot set constant field')")
        lines.append("")
        return
    if meta.presence == "optional":
        lines.append("        if value is None:")
        lines.append(f"            value = {null_literal}")
    if min_literal is not None:
        lines.append(f"        if value < {min_literal}:")
        lines.append("            raise ValueError('value below minValue')")
    if max_literal is not None:
        lines.append(f"        if value > {max_literal}:")
        lines.append("            raise ValueError('value above maxValue')")
    lines.append(
        "        write_primitive("
        f"self.buffer, {offset_expr}, {primitive_type!r}, value, byte_order=BYTE_ORDER)"
    )
    lines.append("")


def _emit_primitive_array_accessor(
    lines: list[str],
    *,
    method: str,
    offset_expr: str,
    primitive_type: str,
    length: int,
    meta: FieldMeta,
    encoder: bool,
) -> None:
    lines.append(f"    def {method}(self):")
    if meta.since_version > 0:
        lines.append(f"        if self.acting_version < {meta.since_version}:")
        lines.append(f"            return np.empty(0, dtype={NUMPY_DTYPE_LITERAL[primitive_type]})")
    lines.append(
        "        return view_primitive_array("
        f"self.buffer, {offset_expr}, {primitive_type!r}, {length}, "
        f"byte_order=BYTE_ORDER, writable={str(encoder)})"
    )
    lines.append("")
    if encoder:
        lines.append(f"    def {method}_set(self, values):")
        if meta.since_version > 0:
            lines.append(f"        if self.acting_version < {meta.since_version}:")
            lines.append("            raise ValueError('field not present in acting version')")
        lines.append(f"        target = self.{method}()")
        lines.append("        np.copyto(target, np.asarray(values, dtype=target.dtype))")
        lines.append("")
        if primitive_type == "char":
            lines.append(f"    def {method}_set_str(self, text):")
            lines.append("        encoded = text.encode('ascii', errors='ignore')")
            lines.append(f"        trimmed = encoded[:{length}]")
            lines.append(f"        padded = trimmed + b'\\x00' * ({length} - len(trimmed))")
            lines.append(f"        self.{method}_set(np.frombuffer(padded, dtype=np.uint8))")
            lines.append("")
    if primitive_type == "char":
        lines.append(f"    def {method}_as_str(self):")
        lines.append(f"        value = self.{method}()")
        if meta.since_version > 0:
            lines.append(f"        if self.acting_version < {meta.since_version}:")
            lines.append("            return ''")
        lines.append("        return bytes(value).decode('ascii', errors='ignore').rstrip('\\x00')")
        lines.append("")


def _emit_field_accessor(
    lines: list[str],
    *,
    schema: SchemaDef,
    field: FieldDef,
    offset_expr: str,
    base_expr: str,
    encoder: bool,
    owner_prefix: str,
) -> None:
    if field.type_name is None:
        raise ValueError(f"field {field.name!r} missing type")
    type_def = schema.types_by_name[field.type_name]
    resolved = _resolve_type(schema, field.type_name)
    meta = _field_meta(schema, field, type_def)
    method = _method_name(field.name)

    if resolved.kind in {"primitive", "enum", "set"} and resolved.length == 1:
        assert resolved.primitive_type is not None
        _emit_scalar_accessor(
            lines,
            method=method,
            offset_expr=offset_expr,
            primitive_type=resolved.primitive_type,
            meta=meta,
            encoder=encoder,
        )
        if resolved.kind == "set":
            lines.append(f"    def {method}_has(self, flag):")
            lines.append(f"        value = self.{method}()")
            lines.append("        return bool(value & flag)")
            lines.append("")
        return

    if resolved.kind == "primitive":
        assert resolved.primitive_type is not None
        _emit_primitive_array_accessor(
            lines,
            method=method,
            offset_expr=offset_expr,
            primitive_type=resolved.primitive_type,
            length=resolved.length,
            meta=meta,
            encoder=encoder,
        )
        return

    if resolved.kind == "composite":
        suffix = "Encoder" if encoder else "Decoder"
        nested_class = f"{class_name(field.type_name)}{suffix}"
        lines.append(f"    def {method}(self):")
        if meta.since_version > 0:
            lines.append(f"        if self.acting_version < {meta.since_version}:")
            lines.append("            return None")
        lines.append(
            f"        return {nested_class}("
            f"self.buffer, {offset_expr}, self.acting_version)"
        )
        lines.append("")
        return

    raise ValueError(f"unsupported field type kind: {resolved.kind!r}")


def _emit_data_accessor(
    lines: list[str],
    *,
    schema: SchemaDef,
    field: FieldDef,
    encoder: bool,
) -> None:
    if field.type_name is None:
        raise ValueError(f"data field {field.name!r} missing type")
    type_def = schema.types_by_name[field.type_name]
    meta = _field_meta(schema, field, type_def)
    method = _method_name(field.name)
    length_type = _var_data_length_type(schema, field.type_name)

    if encoder:
        lines.append(f"    def {method}_set(self, data):")
        if meta.since_version > 0:
            lines.append(f"        if self.acting_version < {meta.since_version}:")
            lines.append("            raise ValueError('field not present in acting version')")
        lines.append("        payload = data.encode('utf-8') if isinstance(data, str) else data")
        lines.append(
            "        next_pos = write_vardata("
            f"self.buffer, self.position_ptr.get(), payload, length_type={length_type!r}, "
            "byte_order=BYTE_ORDER)"
        )
        lines.append("        self.position_ptr.set(next_pos)")
        lines.append("")
        return

    lines.append(f"    def {method}(self):")
    if meta.since_version > 0:
        lines.append(f"        if self.acting_version < {meta.since_version}:")
        lines.append("            return memoryview(b'')")
    lines.append(
        "        data, next_pos = read_vardata("
        f"self.buffer, self.position_ptr.get(), length_type={length_type!r}, "
        "byte_order=BYTE_ORDER)"
    )
    lines.append("        self.position_ptr.set(next_pos)")
    lines.append("        return data")
    lines.append("")
    lines.append(f"    def {method}_as_str(self):")
    if meta.since_version > 0:
        lines.append(f"        if self.acting_version < {meta.since_version}:")
        lines.append("            return ''")
    lines.append(f"        return bytes(self.{method}()).decode('utf-8', errors='ignore')")
    lines.append("")


def _group_class_name(prefix: str, field_name: str, encoder: bool) -> str:
    suffix = "Encoder" if encoder else "Decoder"
    return f"{class_name(prefix)}{class_name(field_name)}{suffix}"


def _emit_group_codecs(
    schema: SchemaDef,
    *,
    prefix: str,
    group_field: FieldDef,
    nested_code: list[str],
) -> tuple[str, str]:
    if group_field.type_name is None:
        raise ValueError(f"group {group_field.name!r} missing dimension type")
    enc_name = _group_class_name(prefix, group_field.name, encoder=True)
    dec_name = _group_class_name(prefix, group_field.name, encoder=False)
    dim_block_type, dim_count_type, _, dim_size = _dimension_spec(schema, group_field.type_name)
    layout = _container_layout(schema, group_field.children)

    enc_methods: list[str] = []
    dec_methods: list[str] = []
    for field, _ in layout.fixed_fields:
        enc_methods.extend(_field_accessor_method_names(schema, field, encoder=True))
        dec_methods.extend(_field_accessor_method_names(schema, field, encoder=False))
    for child in group_field.children:
        if child.kind in {"group", "data"}:
            enc_methods.extend(_field_accessor_method_names(schema, child, encoder=True))
            dec_methods.extend(_field_accessor_method_names(schema, child, encoder=False))
    _assert_no_method_collisions(
        enc_methods,
        class_label=enc_name,
        reserved={"__init__", "next", "__next__", "__iter__"},
    )
    _assert_no_method_collisions(
        dec_methods,
        class_label=dec_name,
        reserved={"__init__", "__next__", "__iter__"},
    )

    # Nested group classes first.
    for child in group_field.children:
        if child.kind == "group":
            child_enc, child_dec = _emit_group_codecs(
                schema,
                prefix=f"{prefix}{class_name(group_field.name)}",
                group_field=child,
                nested_code=nested_code,
            )
            nested_code.extend([child_enc, "", child_dec, ""])

    enc_lines = [
        f"class {enc_name}:",
        f"    BLOCK_LENGTH = {layout.block_length}",
        "    def __init__(self, buffer, position_ptr, count, acting_version=SCHEMA_VERSION):",
        "        self.buffer = to_memoryview(buffer, writable=True)",
        "        self.position_ptr = position_ptr",
        "        self.count = int(count)",
        "        self.index = 0",
        "        self.entry_offset = 0",
        "        self.acting_version = acting_version",
        "",
        "    def next(self):",
        "        if self.index >= self.count:",
        "            raise StopIteration('group cursor exhausted')",
        "        self.entry_offset = self.position_ptr.get()",
        "        self.position_ptr.advance(self.BLOCK_LENGTH)",
        "        self.index += 1",
        "        return self",
        "",
        "    __next__ = next",
        "    def __iter__(self):",
        "        return self",
        "",
    ]

    for field, offset in layout.fixed_fields:
        _emit_field_accessor(
            enc_lines,
            schema=schema,
            field=field,
            offset_expr=f"self.entry_offset + {offset}",
            base_expr="self.entry_offset",
            encoder=True,
            owner_prefix=f"{prefix}{class_name(group_field.name)}",
        )

    for child in group_field.children:
        if child.kind == "group":
            child_enc_name = _group_class_name(
                f"{prefix}{class_name(group_field.name)}", child.name, encoder=True
            )
            if child.type_name is None:
                raise ValueError("nested group missing dimension type")
            child_block_type, child_count_type, _, child_dim_size = _dimension_spec(
                schema, child.type_name
            )
            child_layout = _container_layout(schema, child.children)
            child_meta = _field_meta(schema, child, schema.types_by_name[child.type_name])
            method = _method_name(child.name)
            enc_lines.append(f"    def {method}_begin(self, count):")
            if child_meta.since_version > 0:
                enc_lines.append(f"        if self.acting_version < {child_meta.since_version}:")
                enc_lines.append(
                    "            raise ValueError('field not present in acting version')"
                )
            enc_lines.append("        position = self.position_ptr.get()")
            enc_lines.append(
                "        write_primitive("
                f"self.buffer, position, {child_block_type!r}, {child_layout.block_length}, "
                "byte_order=BYTE_ORDER)"
            )
            enc_lines.append(
                "        write_primitive("
                f"self.buffer, position + {PRIMITIVE_SIZE[child_block_type]}, "
                f"{child_count_type!r}, count, byte_order=BYTE_ORDER)"
            )
            enc_lines.append(f"        self.position_ptr.set(position + {child_dim_size})")
            enc_lines.append(
                f"        return {child_enc_name}("
                "self.buffer, self.position_ptr, count, self.acting_version)"
            )
            enc_lines.append("")
        elif child.kind == "data":
            _emit_data_accessor(enc_lines, schema=schema, field=child, encoder=True)

    dec_lines = [
        f"class {dec_name}:",
        "    def __init__(",
        "        self, buffer, position_ptr, count, block_length,",
        "        acting_version=SCHEMA_VERSION",
        "    ):",
        "        self.buffer = to_memoryview(buffer, writable=False)",
        "        self.position_ptr = position_ptr",
        "        self.count = int(count)",
        "        self.block_length = int(block_length)",
        "        self.index = 0",
        "        self.entry_offset = 0",
        "        self.acting_version = acting_version",
        "",
        "    def __next__(self):",
        "        if self.index >= self.count:",
        "            raise StopIteration",
        "        self.entry_offset = self.position_ptr.get()",
        "        self.position_ptr.advance(self.block_length)",
        "        self.index += 1",
        "        return self",
        "",
        "    def __iter__(self):",
        "        return self",
        "",
    ]

    for field, offset in layout.fixed_fields:
        _emit_field_accessor(
            dec_lines,
            schema=schema,
            field=field,
            offset_expr=f"self.entry_offset + {offset}",
            base_expr="self.entry_offset",
            encoder=False,
            owner_prefix=f"{prefix}{class_name(group_field.name)}",
        )

    for child in group_field.children:
        if child.kind == "group":
            child_dec_name = _group_class_name(
                f"{prefix}{class_name(group_field.name)}", child.name, encoder=False
            )
            if child.type_name is None:
                raise ValueError("nested group missing dimension type")
            child_block_type, child_count_type, _, child_dim_size = _dimension_spec(
                schema, child.type_name
            )
            child_meta = _field_meta(schema, child, schema.types_by_name[child.type_name])
            child_layout = _container_layout(schema, child.children)
            method = _method_name(child.name)
            dec_lines.append(f"    def {method}(self):")
            if child_meta.since_version > 0:
                dec_lines.append(f"        if self.acting_version < {child_meta.since_version}:")
                dec_lines.append(
                    f"            return {child_dec_name}(self.buffer, self.position_ptr, 0, "
                    f"{child_layout.block_length}, self.acting_version)"
                )
            dec_lines.append("        position = self.position_ptr.get()")
            dec_lines.append(
                "        block_length = read_primitive("
                f"self.buffer, position, {child_block_type!r}, byte_order=BYTE_ORDER)"
            )
            dec_lines.append(
                "        count = read_primitive("
                f"self.buffer, position + {PRIMITIVE_SIZE[child_block_type]}, "
                f"{child_count_type!r}, byte_order=BYTE_ORDER)"
            )
            dec_lines.append(f"        self.position_ptr.set(position + {child_dim_size})")
            dec_lines.append(
                f"        return {child_dec_name}("
                "self.buffer, self.position_ptr, count, block_length, self.acting_version)"
            )
            dec_lines.append("")
        elif child.kind == "data":
            _emit_data_accessor(dec_lines, schema=schema, field=child, encoder=False)

    return "\n".join(enc_lines), "\n".join(dec_lines)


def _emit_composite_codec(schema: SchemaDef, type_def: TypeDef, *, encoder: bool) -> str:
    suffix = "Encoder" if encoder else "Decoder"
    class_label = f"{class_name(type_def.name)}{suffix}"
    method_names: list[str] = []
    for member_name, type_name, _, _ in _composite_member_layout(schema, type_def):
        field = FieldDef(name=member_name, id=-1, kind="field", type_name=type_name)
        resolved = _resolve_type(schema, type_name)
        if resolved.kind == "primitive" and resolved.length > 1:
            method = _method_name(member_name)
            method_names.append(method)
            if encoder:
                method_names.append(f"{method}_set")
                if resolved.primitive_type == "char":
                    method_names.append(f"{method}_set_str")
            if resolved.primitive_type == "char":
                method_names.append(f"{method}_as_str")
        else:
            method_names.extend(_field_accessor_method_names(schema, field, encoder=encoder))
    _assert_no_method_collisions(method_names, class_label=class_label, reserved={"__init__"})

    lines = [
        f"class {class_label}:",
        "    def __init__(self, buffer, offset=0, acting_version=SCHEMA_VERSION):",
        f"        self.buffer = to_memoryview(buffer, writable={str(encoder)})",
        "        self.offset = offset",
        "        self.acting_version = acting_version",
        "",
    ]
    for name, type_name, member_len, member_offset in _composite_member_layout(schema, type_def):
        field = FieldDef(name=name, id=-1, kind="field", type_name=type_name)
        resolved = _resolve_type(schema, type_name)
        if resolved.kind == "primitive" and resolved.length > 1:
            resolved_len = resolved.length * member_len
            _emit_primitive_array_accessor(
                lines,
                method=_method_name(name),
                offset_expr=f"self.offset + {member_offset}",
                primitive_type=resolved.primitive_type or "uint8",
                length=resolved_len,
                meta=FieldMeta(0, "required", None, None, None, None),
                encoder=encoder,
            )
        else:
            _emit_field_accessor(
                lines,
                schema=schema,
                field=field,
                offset_expr=f"self.offset + {member_offset}",
                base_expr="self.offset",
                encoder=encoder,
                owner_prefix=class_name(type_def.name),
            )
    return "\n".join(lines)


def _emit_message_codec(
    schema: SchemaDef,
    message: MessageDef,
    *,
    encoder: bool,
    header_size: int,
    nested_code: list[str],
) -> str:
    suffix = "Encoder" if encoder else "Decoder"
    class_label = f"{class_name(message.name)}{suffix}"
    layout = _container_layout(schema, message.fields)
    method_names: list[str] = []
    for field, _ in layout.fixed_fields:
        method_names.extend(_field_accessor_method_names(schema, field, encoder=encoder))
    for field in message.fields:
        if field.kind in {"group", "data"}:
            method_names.extend(_field_accessor_method_names(schema, field, encoder=encoder))
    reserved = {"__init__", "rewind"}
    if encoder:
        reserved.update({"wrap_and_apply_header"})
    else:
        reserved.update({"wrap"})
    _assert_no_method_collisions(method_names, class_label=class_label, reserved=reserved)

    lines = [
        f"class {class_label}:",
        f"    TEMPLATE_ID = {message.id}",
        f"    SCHEMA_ID = {schema.id}",
        f"    SCHEMA_VERSION = {schema.version}",
        "    BLOCK_LENGTH = "
        f"{layout.block_length if message.block_length == 0 else message.block_length}",
        "",
    ]
    if encoder:
        lines.extend(
            [
                "    @classmethod",
                "    def wrap_and_apply_header(cls, buffer, offset=0):",
                "        header = MessageHeaderEncoder(buffer, offset, cls.SCHEMA_VERSION)",
                "        header.blockLength_set(cls.BLOCK_LENGTH)",
                "        header.templateId_set(cls.TEMPLATE_ID)",
                "        header.schemaId_set(cls.SCHEMA_ID)",
                "        header.version_set(cls.SCHEMA_VERSION)",
                "        return cls(",
                f"            buffer, offset + {header_size}, cls.BLOCK_LENGTH,",
                "            cls.SCHEMA_VERSION",
                "        )",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "    @classmethod",
                "    def wrap(",
                "        cls, buffer, offset=0, *, with_header=True,",
                "        acting_block_length=None, acting_version=None",
                "    ):",
                "        if with_header:",
                "            header = MessageHeaderDecoder(buffer, offset, cls.SCHEMA_VERSION)",
                "            if acting_block_length is None:",
                "                acting_block_length = int(header.blockLength())",
                "            if acting_version is None:",
                "                acting_version = int(header.version())",
                f"            base = offset + {header_size}",
                "        else:",
                "            base = offset",
                "        if acting_block_length is None:",
                "            acting_block_length = cls.BLOCK_LENGTH",
                "        if acting_version is None:",
                "            acting_version = cls.SCHEMA_VERSION",
                "        return cls(buffer, base, acting_block_length, acting_version)",
                "",
            ]
        )

    lines.extend(
        [
            "    def __init__(self, buffer, offset=0, acting_block_length=0, acting_version=0):",
            f"        self.buffer = to_memoryview(buffer, writable={str(encoder)})",
            "        self.offset = offset",
            "        self.acting_block_length = int(acting_block_length)",
            "        self.acting_version = int(acting_version)",
            "        self.position_ptr = PositionPointer(offset + self.acting_block_length)",
            "",
            "    def rewind(self):",
            "        self.position_ptr.set(self.offset + self.acting_block_length)",
            "        return self.position_ptr.get()",
            "",
        ]
    )

    for field, offset in layout.fixed_fields:
        _emit_field_accessor(
            lines,
            schema=schema,
            field=field,
            offset_expr=f"self.offset + {offset}",
            base_expr="self.offset",
            encoder=encoder,
            owner_prefix=class_name(message.name),
        )

    for field in message.fields:
        if field.kind == "group":
            enc_group, dec_group = _emit_group_codecs(
                schema,
                prefix=class_name(message.name),
                group_field=field,
                nested_code=nested_code,
            )
            nested_code.extend([enc_group, "", dec_group, ""])
            group_enc_name = _group_class_name(class_name(message.name), field.name, encoder=True)
            group_dec_name = _group_class_name(class_name(message.name), field.name, encoder=False)
            dim_block_type, dim_count_type, _, dim_size = _dimension_spec(
                schema, field.type_name or ""
            )
            child_layout = _container_layout(schema, field.children)
            method = _method_name(field.name)
            if field.type_name is None:
                raise ValueError("group missing dimension type")
            group_meta = _field_meta(schema, field, schema.types_by_name[field.type_name])
            if encoder:
                lines.append(f"    def {method}_begin(self, count):")
                if group_meta.since_version > 0:
                    lines.append(f"        if self.acting_version < {group_meta.since_version}:")
                    lines.append(
                        "            raise ValueError('field not present in acting version')"
                    )
                lines.append("        position = self.position_ptr.get()")
                lines.append(
                    "        write_primitive("
                    f"self.buffer, position, {dim_block_type!r}, {child_layout.block_length}, "
                    "byte_order=BYTE_ORDER)"
                )
                lines.append(
                    "        write_primitive("
                    f"self.buffer, position + {PRIMITIVE_SIZE[dim_block_type]}, "
                    f"{dim_count_type!r}, count, byte_order=BYTE_ORDER)"
                )
                lines.append(f"        self.position_ptr.set(position + {dim_size})")
                lines.append(
                    f"        return {group_enc_name}("
                    "self.buffer, self.position_ptr, count, self.acting_version)"
                )
                lines.append("")
            else:
                lines.append(f"    def {method}(self):")
                if group_meta.since_version > 0:
                    lines.append(f"        if self.acting_version < {group_meta.since_version}:")
                    lines.append(
                        f"            return {group_dec_name}(self.buffer, self.position_ptr, 0, "
                        f"{child_layout.block_length}, self.acting_version)"
                    )
                lines.append("        position = self.position_ptr.get()")
                lines.append(
                    "        block_length = read_primitive("
                    f"self.buffer, position, {dim_block_type!r}, byte_order=BYTE_ORDER)"
                )
                lines.append(
                    "        count = read_primitive("
                    f"self.buffer, position + {PRIMITIVE_SIZE[dim_block_type]}, "
                    f"{dim_count_type!r}, byte_order=BYTE_ORDER)"
                )
                lines.append(f"        self.position_ptr.set(position + {dim_size})")
                lines.append(
                    f"        return {group_dec_name}("
                    "self.buffer, self.position_ptr, count, block_length, self.acting_version)"
                )
                lines.append("")
        elif field.kind == "data":
            _emit_data_accessor(lines, schema=schema, field=field, encoder=encoder)

    return "\n".join(lines)


def emit_module(schema: SchemaDef, module_name: str) -> str:
    """Emit generated Python module text for a parsed schema."""

    header_type = schema.types_by_name[schema.header_type]
    header_size = _resolve_type(schema, schema.header_type).encoded_length
    parts = [
        '"""Generated by pysbe codegen (Phase 5)."""',
        "",
        "from __future__ import annotations",
        "",
        "import numpy as np",
        "",
        "from pysbe.runtime import (",
        "    PositionPointer,",
        "    read_primitive,",
        "    read_vardata,",
        "    to_memoryview,",
        "    view_primitive_array,",
        "    write_primitive,",
        "    write_vardata,",
        ")",
        "",
        f"BYTE_ORDER = {schema.byte_order!r}",
        f"SCHEMA_ID = {schema.id}",
        f"SCHEMA_VERSION = {schema.version}",
        f"HEADER_SIZE = {header_size}",
        "",
        _emit_enum_and_set_types(schema).rstrip(),
    ]

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

    nested_group_code: list[str] = []
    for message in schema.messages:
        parts.append(
            _emit_message_codec(
                schema,
                message,
                encoder=True,
                header_size=header_size,
                nested_code=nested_group_code,
            )
        )
        parts.append("")
        parts.append(
            _emit_message_codec(
                schema,
                message,
                encoder=False,
                header_size=header_size,
                nested_code=nested_group_code,
            )
        )
        parts.append("")

    if nested_group_code:
        parts.extend(nested_group_code)

    body = "\n".join(item for item in parts if item is not None).rstrip() + "\n"
    return f"# module: {module_name}\n# package: {schema.package_name}\n{body}"
