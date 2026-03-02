from __future__ import annotations

from pathlib import Path

from pysbe.ir import (
    Signal,
    collect_fields,
    collect_groups,
    collect_var_data,
    find_end_signal,
    generate_ir,
    get_message_body,
)
from pysbe.parser import parse_schema


def _write_schema(tmp_path: Path) -> Path:
    schema = tmp_path / "schema.xml"
    schema.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="7"
            version="3"
            byteOrder="littleEndian">
          <types>
            <composite name="messageHeader">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="templateId" primitiveType="uint16"/>
              <type name="schemaId" primitiveType="uint16"/>
              <type name="version" primitiveType="uint16"/>
            </composite>
            <composite name="groupSizeEncoding">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="numInGroup" primitiveType="uint16"/>
            </composite>
            <composite name="Coord">
              <type name="x" primitiveType="int32"/>
              <type name="y" primitiveType="int32"/>
            </composite>
            <composite name="VarString">
              <type name="length" primitiveType="uint8"/>
              <type name="varData" primitiveType="char"/>
            </composite>
          </types>
          <sbe:message name="Quote" id="1">
            <field name="seqNum" id="1" type="uint64"/>
            <group name="legs" id="2">
              <field name="coord" id="1" type="Coord"/>
            </group>
            <data name="text" id="3" type="VarString"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )
    return schema


def test_generate_ir_message_tokens_and_traversal(tmp_path: Path) -> None:
    schema = parse_schema(_write_schema(tmp_path))
    ir = generate_ir(schema)
    message_tokens = ir.message(1)
    assert message_tokens is not None

    signals = [token.signal for token in message_tokens]
    assert signals[0] == Signal.BEGIN_MESSAGE
    assert signals[-1] == Signal.END_MESSAGE
    assert Signal.BEGIN_GROUP in signals
    assert Signal.BEGIN_VAR_DATA in signals

    fields = collect_fields(message_tokens)
    assert len(fields) == 2
    assert fields[0][0].name == "seqNum"
    assert fields[1][0].name == "coord"

    groups = collect_groups(message_tokens)
    assert len(groups) == 1
    assert groups[0][0].name == "legs"

    var_data = collect_var_data(message_tokens)
    assert len(var_data) == 1
    assert var_data[0][0].name == "text"

    group_start = next(
        idx for idx, token in enumerate(message_tokens) if token.signal == Signal.BEGIN_GROUP
    )
    group_end = find_end_signal(
        message_tokens,
        group_start,
        Signal.BEGIN_GROUP,
        Signal.END_GROUP,
    )
    assert message_tokens[group_end].signal == Signal.END_GROUP

    body = get_message_body(ir, 1)
    assert body[0].signal == Signal.BEGIN_FIELD
    assert body[-1].signal == Signal.END_VAR_DATA


def test_generate_ir_captures_type_streams_and_component_counts(tmp_path: Path) -> None:
    schema = parse_schema(_write_schema(tmp_path))
    ir = generate_ir(schema)

    assert "Coord" in ir.types_by_name
    coord_tokens = ir.types_by_name["Coord"]
    assert coord_tokens[0].signal == Signal.BEGIN_COMPOSITE
    assert coord_tokens[-1].signal == Signal.END_COMPOSITE
    assert coord_tokens[0].component_token_count == len(coord_tokens)

    header_tokens = ir.header_tokens
    assert header_tokens[0].signal == Signal.BEGIN_COMPOSITE
    assert header_tokens[0].component_token_count == len(header_tokens)
