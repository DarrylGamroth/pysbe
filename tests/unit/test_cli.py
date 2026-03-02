from __future__ import annotations

from pathlib import Path

import pytest

from pysbe.cli import main


def _write_schema(path: Path) -> None:
    path.write_text(
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
          <sbe:message name="Ping" id="1"/>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_generate(tmp_path: Path) -> None:
    schema = tmp_path / "schema.xml"
    _write_schema(schema)
    output_dir = tmp_path / "generated"

    exit_code = main(["generate", str(schema), "-o", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "Baseline.py").is_file()


def test_cli_generate_ir_to_file(tmp_path: Path) -> None:
    schema = tmp_path / "schema.xml"
    _write_schema(schema)
    output = tmp_path / "ir.json"

    exit_code = main(["generate-ir", str(schema), "-o", str(output)])

    assert exit_code == 0
    assert output.is_file()
    assert "Ping" in output.read_text(encoding="utf-8")
