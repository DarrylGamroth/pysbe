from __future__ import annotations

from pathlib import Path

from pysbe.interop.java import find_java_prerequisites


def test_find_java_prerequisites_accepts_env_jar_without_ref_dir(
    tmp_path: Path, monkeypatch
) -> None:
    jar_path = tmp_path / "sbe-all.jar"
    jar_path.write_bytes(b"jar")

    monkeypatch.setenv("SBE_JAR_PATH", str(jar_path))
    monkeypatch.setattr("pysbe.interop.java.shutil.which", lambda _: "/usr/bin/tool")

    prereq = find_java_prerequisites(ref_dir=tmp_path / "missing-reference-dir")

    assert prereq is not None
    assert prereq.jar_path == jar_path
    assert prereq.ref_dir is None
