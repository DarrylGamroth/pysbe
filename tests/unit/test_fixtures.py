from __future__ import annotations

from pathlib import Path

from pysbe.fixtures import (
    ensure_fixture_layout,
    import_java_fixture,
    import_schema_fixture,
    list_fixtures,
    sync_fixture_manifest,
)


def test_fixture_layout_and_manifest(tmp_path: Path) -> None:
    layout = ensure_fixture_layout(root=tmp_path)
    assert layout["schemas"].is_dir()
    assert layout["java"].is_dir()

    schema_source = tmp_path / "sample.xml"
    schema_source.write_text("<messageSchema id='1'/>", encoding="utf-8")
    java_source = tmp_path / "car.bin"
    java_source.write_bytes(b"abc")

    import_schema_fixture(schema_source, root=tmp_path)
    import_java_fixture(java_source, root=tmp_path)

    fixtures = list_fixtures(root=tmp_path)
    assert fixtures["schemas"] == ["sample.xml"]
    assert fixtures["java"] == ["car.bin"]

    manifest = sync_fixture_manifest(root=tmp_path)
    assert manifest.is_file()
    assert "sample.xml" in manifest.read_text(encoding="utf-8")
