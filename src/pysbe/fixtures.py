"""Fixture management helpers for tests and interoperability workflows."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Final

SCHEMA_DIR_NAME: Final[str] = "schemas"
JAVA_DIR_NAME: Final[str] = "java"
MANIFEST_FILENAME: Final[str] = "manifest.json"


def project_root() -> Path:
    """Return the repository root inferred from the installed source layout."""

    return Path(__file__).resolve().parents[2]


def fixtures_root(root: Path | None = None) -> Path:
    """Return the fixture root directory."""

    base = root if root is not None else project_root()
    return base / "tests" / "fixtures"


def ensure_fixture_layout(root: Path | None = None) -> dict[str, Path]:
    """Create required fixture directories if missing and return their paths."""

    base = fixtures_root(root)
    schemas = base / SCHEMA_DIR_NAME
    java = base / JAVA_DIR_NAME
    schemas.mkdir(parents=True, exist_ok=True)
    java.mkdir(parents=True, exist_ok=True)
    return {SCHEMA_DIR_NAME: schemas, JAVA_DIR_NAME: java}


def _copy_fixture(source: Path, destination_dir: Path, name: str | None = None) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"Fixture file not found: {source}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / (name if name else source.name)
    shutil.copy2(source, destination)
    return destination


def import_schema_fixture(
    source: str | Path,
    name: str | None = None,
    root: Path | None = None,
) -> Path:
    """Copy a schema fixture into `tests/fixtures/schemas`."""

    layout = ensure_fixture_layout(root)
    return _copy_fixture(Path(source), layout[SCHEMA_DIR_NAME], name=name)


def import_java_fixture(
    source: str | Path,
    name: str | None = None,
    root: Path | None = None,
) -> Path:
    """Copy a Java-generated binary fixture into `tests/fixtures/java`."""

    layout = ensure_fixture_layout(root)
    return _copy_fixture(Path(source), layout[JAVA_DIR_NAME], name=name)


def list_fixtures(root: Path | None = None) -> dict[str, list[str]]:
    """List known fixtures by category."""

    layout = ensure_fixture_layout(root)
    schemas = sorted(path.name for path in layout[SCHEMA_DIR_NAME].iterdir() if path.is_file())
    java = sorted(path.name for path in layout[JAVA_DIR_NAME].iterdir() if path.is_file())
    return {SCHEMA_DIR_NAME: schemas, JAVA_DIR_NAME: java}


def sync_fixture_manifest(root: Path | None = None) -> Path:
    """Write `tests/fixtures/manifest.json` from the current fixture directory contents."""

    base = fixtures_root(root)
    data = list_fixtures(root)
    manifest = base / MANIFEST_FILENAME
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
