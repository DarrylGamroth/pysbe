from __future__ import annotations

import struct
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
import pytest

from pysbe.generate import generate


def _load_module(path: Path, module_name: str):
    spec = spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_codecs_roundtrip_smoke(tmp_path: Path) -> None:
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
            <enum name="Side" encodingType="uint8">
              <validValue name="Buy">1</validValue>
              <validValue name="Sell">2</validValue>
            </enum>
            <set name="Flags" encodingType="uint8">
              <choice name="Fast">0</choice>
              <choice name="Agg">1</choice>
            </set>
            <type name="Code6" primitiveType="char" length="6"/>
            <type name="Levels" primitiveType="uint32" length="3"/>
            <composite name="Engine">
              <type name="capacity" primitiveType="uint16"/>
              <type name="cylinders" primitiveType="uint8"/>
            </composite>
          </types>
          <sbe:message name="Order" id="1">
            <field name="seqNum" id="1" type="uint64"/>
            <field name="side" id="2" type="Side"/>
            <field name="flags" id="3" type="Flags"/>
            <field name="code" id="4" type="Code6"/>
            <field name="levels" id="5" type="Levels"/>
            <field name="engine" id="6" type="Engine"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    artifact = generate(schema_path=schema_path, output_dir=tmp_path)
    module = _load_module(artifact.output_path, "generated_baseline")

    buffer = bytearray(256)
    enc = module.OrderEncoder.wrap_and_apply_header(buffer, 0)
    enc.seqNum_set(12345)
    enc.side_set(module.Side.BUY)
    enc.flags_set(module.Flags.FAST | module.Flags.AGG)
    enc.code_set_str("ABC123")
    enc.levels_set([10, 20, 30])
    engine = enc.engine()
    engine.capacity_set(2200)
    engine.cylinders_set(6)

    dec = module.OrderDecoder.wrap(buffer, 0)
    assert dec.seqNum() == 12345
    assert dec.side() == module.Side.BUY
    assert dec.flags_has(module.Flags.FAST)
    assert dec.flags_has(module.Flags.AGG)
    assert dec.code_as_str() == "ABC123"
    assert list(dec.levels()) == [10, 20, 30]
    assert np.shares_memory(dec.levels(), np.frombuffer(buffer, dtype=np.uint8))

    engine_dec = dec.engine()
    assert engine_dec.capacity() == 2200
    assert engine_dec.cylinders() == 6


def test_generate_rejects_sanitized_method_name_collisions(tmp_path: Path) -> None:
    schema_path = tmp_path / "collision.xml"
    schema_path.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="collision"
            id="1"
            version="0">
          <types>
            <composite name="messageHeader">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="templateId" primitiveType="uint16"/>
              <type name="schemaId" primitiveType="uint16"/>
              <type name="version" primitiveType="uint16"/>
            </composite>
          </types>
          <sbe:message name="M" id="1">
            <field name="class" id="1" type="uint32"/>
            <field name="class_" id="2" type="uint32"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate generated method name"):
        generate(schema_path=schema_path, output_dir=tmp_path)


def test_generated_decoder_gates_group_and_vardata_by_since_version(tmp_path: Path) -> None:
    schema_path = tmp_path / "versioned.xml"
    schema_path.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="versioned"
            id="11"
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
          </types>
          <sbe:message name="Trade" id="1">
            <field name="seqNum" id="1" type="uint32"/>
            <group name="legs" id="2" sinceVersion="2">
              <field name="px" id="1" type="uint32"/>
            </group>
            <data name="text" id="3" type="VarString" sinceVersion="2"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    artifact = generate(schema_path=schema_path, output_dir=tmp_path)
    module = _load_module(artifact.output_path, "generated_versioned")

    payload = bytearray(32)
    struct.pack_into("<HHHH", payload, 0, 4, 1, 11, 0)  # header with acting version 0
    struct.pack_into("<I", payload, 8, 77)  # seqNum

    dec = module.TradeDecoder.wrap(bytes(payload[:12]), 0)
    assert dec.seqNum() == 77
    legs = dec.legs()
    assert legs.count == 0
    assert list(legs) == []
    assert dec.text_as_str() == ""


def test_generated_optional_scalar_exposes_null_helpers(tmp_path: Path) -> None:
    schema_path = tmp_path / "optional.xml"
    schema_path.write_text(
        """
        <sbe:messageSchema xmlns:sbe="http://fixprotocol.io/2016/sbe"
            package="optional"
            id="22"
            version="0"
            byteOrder="littleEndian">
          <types>
            <composite name="messageHeader">
              <type name="blockLength" primitiveType="uint16"/>
              <type name="templateId" primitiveType="uint16"/>
              <type name="schemaId" primitiveType="uint16"/>
              <type name="version" primitiveType="uint16"/>
            </composite>
            <type name="OptU16" primitiveType="uint16" presence="optional" nullValue="65535"/>
          </types>
          <sbe:message name="M" id="1">
            <field name="qty" id="1" type="OptU16"/>
          </sbe:message>
        </sbe:messageSchema>
        """.strip(),
        encoding="utf-8",
    )

    artifact = generate(schema_path=schema_path, output_dir=tmp_path)
    module = _load_module(artifact.output_path, "generated_optional")

    buffer = bytearray(64)
    enc = module.MEncoder.wrap_and_apply_header(buffer, 0)
    enc.qty_set(None)

    dec = module.MDecoder.wrap(buffer, 0)
    assert dec.qty() == 65535
    assert dec.qty_is_null()
    assert dec.qty_or_none() is None
