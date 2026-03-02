from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from pysbe.generate import generate


def _load_module(path: Path, module_name: str):
    spec = spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase5_groups_vardata_and_version_gating(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.xml"
    schema_path.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="phase5"
            id="55"
            version="2"
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
            <composite name="VarString">
              <type name="length" primitiveType="uint8"/>
              <type name="varData" primitiveType="char"/>
            </composite>
            <type name="OptionalU16" primitiveType="uint16" presence="optional" nullValue="65535"/>
            <type name="ConstU8" primitiveType="uint8" presence="constant" value="7"/>
          </types>
          <sbe:message name="Trade" id="1">
            <field name="seqNum" id="1" type="uint64"/>
            <field name="optionalValue" id="2" type="OptionalU16"/>
            <field name="constValue" id="3" type="ConstU8"/>
            <field name="futureValue" id="4" type="uint32" sinceVersion="5"/>
            <group name="legs" id="10">
              <field name="px" id="1" type="int64"/>
              <group name="tags" id="2">
                <field name="code" id="1" type="uint16"/>
              </group>
              <data name="note" id="3" type="VarString"/>
            </group>
            <data name="text" id="20" type="VarString"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    artifact = generate(schema_path=schema_path, output_dir=tmp_path)
    module = _load_module(artifact.output_path, "generated_phase5")

    buffer = bytearray(1024)
    enc = module.TradeEncoder.wrap_and_apply_header(buffer, 0)
    enc.seqNum_set(999)
    enc.optionalValue_set(42)

    with pytest.raises(ValueError):
        enc.constValue_set(1)
    with pytest.raises(ValueError):
        enc.futureValue_set(123)

    legs = enc.legs_begin(1)
    leg = legs.next()
    leg.px_set(10_000)
    tags = leg.tags_begin(1)
    tag = tags.next()
    tag.code_set(77)
    leg.note_set("leg-1")
    enc.text_set("hello")

    dec = module.TradeDecoder.wrap(buffer, 0)
    assert dec.seqNum() == 999
    assert dec.optionalValue() == 42
    assert dec.constValue() == 7
    assert dec.futureValue() == 4_294_967_295

    decoded_legs = dec.legs()
    decoded_leg = next(decoded_legs)
    assert decoded_leg.px() == 10_000
    decoded_tags = decoded_leg.tags()
    decoded_tag = next(decoded_tags)
    assert decoded_tag.code() == 77
    assert decoded_leg.note_as_str() == "leg-1"
    assert dec.text_as_str() == "hello"
