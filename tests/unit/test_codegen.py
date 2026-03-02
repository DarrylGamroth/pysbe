from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np

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
