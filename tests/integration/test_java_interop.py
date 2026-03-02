from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from pysbe import (
    DEFAULT_JAVA_INTEROP_VALUES,
    JavaInteropUnavailable,
    encode_fixture_with_java,
    find_java_prerequisites,
    generate,
    verify_payload_with_java,
)


def _load_module(path: Path, module_name: str):
    spec = spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_java_python_binary_interop(tmp_path: Path) -> None:
    prereq = find_java_prerequisites()
    if prereq is None:
        pytest.skip("java/javac/sbe-all jar unavailable for interop test")

    schema_path = Path(__file__).resolve().parents[1] / "fixtures" / "schemas" / "java-interop.xml"
    if not schema_path.is_file():
        pytest.skip(f"missing schema fixture: {schema_path}")

    # Generate Python codecs from schema.
    artifact = generate(schema_path=schema_path, output_dir=tmp_path)
    module = _load_module(artifact.output_path, "generated_java_interop")

    # Java -> Python decode.
    java_fixture = tmp_path / "java-fixture.bin"
    try:
        encode_fixture_with_java(schema_path, java_fixture)
    except JavaInteropUnavailable as exc:
        pytest.skip(str(exc))

    java_payload = java_fixture.read_bytes()
    decoder = module.InteropMessageDecoder.wrap(java_payload, 0)
    assert decoder.seqNum() == int(DEFAULT_JAVA_INTEROP_VALUES["seqNum"])
    assert decoder.qty() == int(DEFAULT_JAVA_INTEROP_VALUES["qty"])
    assert decoder.price() == int(DEFAULT_JAVA_INTEROP_VALUES["price"])

    # Python -> Java verify.
    py_buffer = bytearray(256)
    encoder = module.InteropMessageEncoder.wrap_and_apply_header(py_buffer, 0)
    encoder.seqNum_set(int(DEFAULT_JAVA_INTEROP_VALUES["seqNum"]))
    encoder.qty_set(int(DEFAULT_JAVA_INTEROP_VALUES["qty"]))
    encoder.price_set(int(DEFAULT_JAVA_INTEROP_VALUES["price"]))

    payload_length = module.HEADER_SIZE + module.InteropMessageEncoder.BLOCK_LENGTH
    py_payload_path = tmp_path / "python-payload.bin"
    py_payload_path.write_bytes(bytes(py_buffer[:payload_length]))

    verify_payload_with_java(schema_path, py_payload_path)
