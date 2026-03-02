from __future__ import annotations

from pathlib import Path

from pysbe.generate import generate, generate_ir_file


def test_generate_writes_placeholder_module(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.xml"
    schema_path.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="baseline"
            id="1"
            version="0"
            byteOrder="littleEndian">
          <types>
            <composite name="messageHeader">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="templateId" primitiveType="uint16"/>
              <type name="schemaId" primitiveType="uint16"/>
              <type name="version" primitiveType="uint16"/>
            </composite>
          </types>
          <sbe:message name="Ping" id="1">
            <field name="value" id="1" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    output_dir = tmp_path / "generated"
    artifact = generate(schema_path=schema_path, output_dir=output_dir)

    assert artifact.module_name == "Baseline"
    assert artifact.output_path.is_file()
    content = artifact.output_path.read_text(encoding="utf-8")
    assert "class PingEncoder" in content
    assert "class PingDecoder" in content
    assert "class MessageHeaderEncoder" in content


def test_generate_ir_file_extracts_basic_metadata(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.xml"
    schema_path.write_text(
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
          </types>
          <sbe:message name="Ping" id="1"/>
          <sbe:message name="Pong" id="2"/>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    ir = generate_ir_file(schema_path)

    assert ir["package"] == "baseline"
    assert ir["id"] == 7
    assert ir["version"] == 3
    assert ir["messages"] == ["Ping", "Pong"]
    assert ir["header_token_count"] > 0
    assert ir["message_token_counts"]["1"] > 0
