"""IR generation from parsed schema models."""

from __future__ import annotations

from dataclasses import replace

from pysbe.ir.model import Encoding, IrSchema, IrToken, PrimitiveType, Signal
from pysbe.parser import FieldDef, SchemaDef, TypeDef, ValidationError

BEGIN_END_SIGNALS: dict[Signal, Signal] = {
    Signal.BEGIN_MESSAGE: Signal.END_MESSAGE,
    Signal.BEGIN_FIELD: Signal.END_FIELD,
    Signal.BEGIN_GROUP: Signal.END_GROUP,
    Signal.BEGIN_VAR_DATA: Signal.END_VAR_DATA,
    Signal.BEGIN_COMPOSITE: Signal.END_COMPOSITE,
    Signal.BEGIN_ENUM: Signal.END_ENUM,
    Signal.BEGIN_SET: Signal.END_SET,
}


def _encoding_for_type(type_def: TypeDef | None, *, byte_order: str) -> Encoding:
    if type_def is None:
        return Encoding(byte_order=byte_order)
    primitive = PrimitiveType.from_name(type_def.primitive_type)
    return Encoding(primitive_type=primitive, byte_order=byte_order)


def _update_component_token_counts(tokens: list[IrToken]) -> list[IrToken]:
    begin_stack: list[tuple[int, Signal]] = []
    for index, token in enumerate(tokens):
        if token.signal in BEGIN_END_SIGNALS:
            begin_stack.append((index, token.signal))
            continue
        if token.signal in BEGIN_END_SIGNALS.values():
            if not begin_stack:
                continue
            begin_index, begin_signal = begin_stack.pop()
            expected_end = BEGIN_END_SIGNALS[begin_signal]
            if token.signal != expected_end:
                continue
            count = index - begin_index + 1
            tokens[begin_index] = replace(tokens[begin_index], component_token_count=count)
    return tokens


def _clone_tokens(tokens: list[IrToken]) -> list[IrToken]:
    return [replace(token) for token in tokens]


def _emit_type_tokens(
    schema: SchemaDef,
    type_name: str,
    *,
    byte_order: str,
    type_cache: dict[str, list[IrToken]],
    active_types: set[str] | None = None,
) -> list[IrToken]:
    if type_name in type_cache:
        return _clone_tokens(type_cache[type_name])

    if active_types is None:
        active_types = set()
    if type_name in active_types:
        raise ValidationError(f"cyclic type reference detected for {type_name!r}")
    active_types.add(type_name)

    type_def = schema.types_by_name.get(type_name)
    if type_def is None:
        # Primitive type
        tokens = [
            IrToken(
                signal=Signal.ENCODING,
                name=type_name,
                encoded_length=1,
                encoding=Encoding(
                    primitive_type=PrimitiveType.from_name(type_name),
                    byte_order=byte_order,
                ),
            )
        ]
        active_types.remove(type_name)
        return tokens

    if type_def.kind in {"primitive", "type"}:
        tokens = [
            IrToken(
                signal=Signal.ENCODING,
                name=type_def.name,
                referenced_name=type_def.name,
                encoded_length=1,
                encoding=_encoding_for_type(type_def, byte_order=byte_order),
            )
        ]
        active_types.remove(type_name)
        return tokens

    if type_def.kind == "enum":
        tokens = [
            IrToken(
                signal=Signal.BEGIN_ENUM,
                name=type_def.name,
                referenced_name=type_def.name,
                encoding=_encoding_for_type(type_def, byte_order=byte_order),
            ),
            IrToken(
                signal=Signal.END_ENUM,
                name=type_def.name,
                referenced_name=type_def.name,
                encoding=_encoding_for_type(type_def, byte_order=byte_order),
            ),
        ]
        tokens = _update_component_token_counts(tokens)
        type_cache[type_name] = _clone_tokens(tokens)
        active_types.remove(type_name)
        return _clone_tokens(tokens)

    if type_def.kind == "set":
        tokens = [
            IrToken(
                signal=Signal.BEGIN_SET,
                name=type_def.name,
                referenced_name=type_def.name,
                encoding=_encoding_for_type(type_def, byte_order=byte_order),
            ),
            IrToken(
                signal=Signal.END_SET,
                name=type_def.name,
                referenced_name=type_def.name,
                encoding=_encoding_for_type(type_def, byte_order=byte_order),
            ),
        ]
        tokens = _update_component_token_counts(tokens)
        type_cache[type_name] = _clone_tokens(tokens)
        active_types.remove(type_name)
        return _clone_tokens(tokens)

    if type_def.kind != "composite":
        raise ValidationError(f"unsupported type kind {type_def.kind!r} for {type_name!r}")

    tokens = [
        IrToken(
            signal=Signal.BEGIN_COMPOSITE,
            name=type_def.name,
            referenced_name=type_def.name,
            encoding=_encoding_for_type(type_def, byte_order=byte_order),
        )
    ]
    for member in type_def.members:
        member_tokens = _emit_type_tokens(
            schema,
            member.type_name,
            byte_order=byte_order,
            type_cache=type_cache,
            active_types=active_types,
        )
        tokens.extend(member_tokens)
    tokens.append(
        IrToken(
            signal=Signal.END_COMPOSITE,
            name=type_def.name,
            referenced_name=type_def.name,
            encoding=_encoding_for_type(type_def, byte_order=byte_order),
        )
    )
    tokens = _update_component_token_counts(tokens)
    type_cache[type_name] = _clone_tokens(tokens)
    active_types.remove(type_name)
    return _clone_tokens(tokens)


def _emit_field_tokens(
    schema: SchemaDef,
    field: FieldDef,
    *,
    byte_order: str,
    type_cache: dict[str, list[IrToken]],
) -> list[IrToken]:
    if field.kind == "group":
        tokens = [IrToken(signal=Signal.BEGIN_GROUP, name=field.name, id=field.id)]
        if field.type_name is not None:
            tokens.extend(
                _emit_type_tokens(
                    schema,
                    field.type_name,
                    byte_order=byte_order,
                    type_cache=type_cache,
                )
            )
        for child in field.children:
            tokens.extend(
                _emit_field_tokens(
                    schema,
                    child,
                    byte_order=byte_order,
                    type_cache=type_cache,
                )
            )
        tokens.append(IrToken(signal=Signal.END_GROUP, name=field.name, id=field.id))
        return tokens

    if field.kind == "data":
        tokens = [IrToken(signal=Signal.BEGIN_VAR_DATA, name=field.name, id=field.id)]
        if field.type_name is not None:
            tokens.extend(
                _emit_type_tokens(
                    schema,
                    field.type_name,
                    byte_order=byte_order,
                    type_cache=type_cache,
                )
            )
        tokens.append(IrToken(signal=Signal.END_VAR_DATA, name=field.name, id=field.id))
        return tokens

    tokens = [IrToken(signal=Signal.BEGIN_FIELD, name=field.name, id=field.id)]
    if field.type_name is not None:
        tokens.extend(
            _emit_type_tokens(
                schema,
                field.type_name,
                byte_order=byte_order,
                type_cache=type_cache,
            )
        )
    tokens.append(IrToken(signal=Signal.END_FIELD, name=field.name, id=field.id))
    return tokens


def generate_ir(schema: SchemaDef) -> IrSchema:
    """Generate IR token streams for header, messages, and named schema types."""

    byte_order = schema.byte_order
    type_cache: dict[str, list[IrToken]] = {}

    header_tokens = _emit_type_tokens(
        schema,
        schema.header_type,
        byte_order=byte_order,
        type_cache=type_cache,
    )
    header_tokens = _update_component_token_counts(header_tokens)

    messages_by_id: dict[int, list[IrToken]] = {}
    for message in schema.messages:
        message_tokens = [
            IrToken(
                signal=Signal.BEGIN_MESSAGE,
                name=message.name,
                id=message.id,
                encoded_length=message.block_length,
            )
        ]
        for field in message.fields:
            message_tokens.extend(
                _emit_field_tokens(
                    schema,
                    field,
                    byte_order=byte_order,
                    type_cache=type_cache,
                )
            )
        message_tokens.append(
            IrToken(
                signal=Signal.END_MESSAGE,
                name=message.name,
                id=message.id,
                encoded_length=message.block_length,
            )
        )
        messages_by_id[message.id] = _update_component_token_counts(message_tokens)

    # Capture named non-primitive types (excluding built-in primitives already in schema types map).
    primitive_names = {
        primitive.value for primitive in PrimitiveType if primitive != PrimitiveType.NONE
    }
    named_types: dict[str, list[IrToken]] = {}
    for type_name, type_def in sorted(schema.types_by_name.items()):
        if type_name in primitive_names:
            continue
        if type_def.kind == "primitive":
            continue
        named_types[type_name] = _emit_type_tokens(
            schema,
            type_name,
            byte_order=byte_order,
            type_cache=type_cache,
        )

    return IrSchema(
        package_name=schema.package_name,
        id=schema.id,
        version=schema.version,
        byte_order=schema.byte_order,
        header_tokens=header_tokens,
        messages_by_id=messages_by_id,
        types_by_name=named_types,
    )
