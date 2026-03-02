from __future__ import annotations

from pathlib import Path

import pytest

from pysbe.parser import ValidationError, parse_schema


def _write_schema(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "schema.xml"
    path.write_text(xml.strip(), encoding="utf-8")
    return path


def _header_types() -> str:
    return """
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
    </types>
    """


def test_parse_schema_returns_model(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="2"
            byteOrder="littleEndian">
          {_header_types()}
          <sbe:message name="Ping" id="1">
            <field name="value" id="1" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    parsed = parse_schema(schema)

    assert parsed.package_name == "baseline"
    assert parsed.id == 1
    assert parsed.version == 2
    assert parsed.header_type == "messageHeader"
    assert [message.name for message in parsed.messages] == ["Ping"]
    assert parsed.messages[0].fields[0].name == "value"


def test_parse_schema_rejects_duplicate_message_ids(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="Ping" id="1"/>
          <sbe:message name="Pong" id="1"/>
        </sbe:messageSchema>
        """,
    )

    with pytest.raises(ValidationError, match="duplicate message id"):
        parse_schema(schema)


def test_parse_schema_rejects_unknown_field_type(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="Ping" id="1">
            <field name="value" id="1" type="missingType"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    with pytest.raises(ValidationError, match="unknown type"):
        parse_schema(schema)


def test_parse_schema_enforces_field_group_data_ordering(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="Ping" id="1">
            <group name="items" id="1">
              <field name="value" id="1" type="uint32"/>
            </group>
            <field name="tail" id="2" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    with pytest.raises(ValidationError, match="ordering"):
        parse_schema(schema)


def test_parse_schema_respects_warning_policy(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="class" id="1">
            <field name="value" id="1" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    parsed = parse_schema(schema, suppress_warnings=True)
    assert parsed.warnings

    with pytest.raises(ValidationError, match="valid Python identifier"):
        parse_schema(schema, warnings_fatal=True, suppress_warnings=True)


def test_parse_schema_parses_inline_composite_members(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          <types>
            <composite name="messageHeader">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="templateId" primitiveType="uint16"/>
              <type name="schemaId" primitiveType="uint16"/>
              <type name="version" primitiveType="uint16"/>
            </composite>
            <composite name="Comp">
              <enum name="side" encodingType="uint8">
                <validValue name="Buy">1</validValue>
              </enum>
              <type name="qty" primitiveType="uint32"/>
            </composite>
          </types>
          <sbe:message name="M" id="1">
            <field name="c" id="1" type="Comp"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    parsed = parse_schema(schema)
    comp = parsed.types_by_name["Comp"]

    assert [member.name for member in comp.members] == ["side", "qty"]
    assert parsed.types_by_name["Comp.side"].kind == "enum"
    assert parsed.types_by_name["Comp.qty"].kind == "type"


def test_parse_schema_enforces_symbolic_names_when_validate_enabled(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="Ping" id="1">
            <field name="bad-name" id="1" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    with pytest.raises(ValidationError, match="symbolicName pattern"):
        parse_schema(schema, validate=True, suppress_warnings=True)


def test_parse_schema_relaxes_symbolic_name_check_when_validate_disabled(tmp_path: Path) -> None:
    schema = _write_schema(
        tmp_path,
        f"""
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0">
          {_header_types()}
          <sbe:message name="Ping" id="1">
            <field name="bad-name" id="1" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """,
    )

    parsed = parse_schema(schema, validate=False, suppress_warnings=True)
    assert any("symbolicName pattern" in warning for warning in parsed.warnings)
