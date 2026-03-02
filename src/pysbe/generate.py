"""Phase 0 generation entry points."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pysbe.codegen import generate_from_schema
from pysbe.ir import generate_ir
from pysbe.parser import parse_schema


@dataclass(frozen=True)
class GeneratedArtifact:
    """Metadata for a generated module artifact."""

    module_name: str
    schema_path: Path
    output_path: Path


def _sanitize_identifier(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned:
        cleaned = "Schema"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _derive_module_name(package_name: str, schema_path: Path) -> str:
    if package_name:
        parts = [part for part in re.split(r"[^A-Za-z0-9]+", package_name) if part]
        if parts:
            return _sanitize_identifier("".join(p.capitalize() for p in parts))
    return _sanitize_identifier(schema_path.stem.capitalize())


def generate(
    schema_path: str | Path,
    output_dir: str | Path,
    module_name: str | None = None,
    validate: bool = True,
    warnings_fatal: bool = False,
    suppress_warnings: bool = False,
    overwrite: bool = False,
) -> GeneratedArtifact:
    """Generate Python codec module from an SBE schema."""

    schema = Path(schema_path)
    schema_def = parse_schema(
        schema,
        validate=validate,
        warnings_fatal=warnings_fatal,
        suppress_warnings=suppress_warnings,
    )
    resolved_module_name = (
        _sanitize_identifier(module_name)
        if module_name
        else _derive_module_name(schema_def.package_name, schema)
    )
    resolved_module_name, output_path, _ = generate_from_schema(
        schema_def,
        output_dir=output_dir,
        module_name=resolved_module_name,
        overwrite=overwrite,
    )

    return GeneratedArtifact(
        module_name=resolved_module_name,
        schema_path=schema,
        output_path=output_path,
    )


def generate_ir_file(schema_path: str | Path) -> dict[str, Any]:
    """Return schema IR summary for tooling and CLI output."""

    schema = Path(schema_path)
    schema_def = parse_schema(schema)
    schema_ir = generate_ir(schema_def)

    return {
        "schema_path": str(schema),
        "package": schema_ir.package_name,
        "id": schema_ir.id,
        "version": schema_ir.version,
        "byte_order": schema_ir.byte_order,
        "messages": [message.name for message in schema_def.messages],
        "header_token_count": len(schema_ir.header_tokens),
        "message_token_counts": {
            str(message_id): len(tokens)
            for message_id, tokens in sorted(schema_ir.messages_by_id.items())
        },
        "type_token_counts": {
            name: len(tokens) for name, tokens in sorted(schema_ir.types_by_name.items())
        },
    }
