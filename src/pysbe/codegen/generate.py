"""Codegen orchestration helpers."""

from __future__ import annotations

from pathlib import Path

from pysbe.codegen.emitter import emit_module
from pysbe.codegen.naming import class_name, sanitize_identifier
from pysbe.parser import SchemaDef


def module_name_from_schema(schema: SchemaDef) -> str:
    """Derive generated module name from schema package."""

    if schema.package_name:
        return class_name(schema.package_name.replace(".", "_"))
    return "Schema"


def generate_from_schema(
    schema: SchemaDef,
    *,
    output_dir: str | Path,
    module_name: str | None = None,
    overwrite: bool = False,
) -> tuple[str, Path, str]:
    """Generate Python codec module text and write it to disk."""

    if module_name:
        resolved_name = sanitize_identifier(module_name)
    else:
        resolved_name = module_name_from_schema(schema)
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    output_path = output_base / f"{resolved_name}.py"
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_path}. Pass overwrite=True to replace it."
        )

    code = emit_module(schema, resolved_name)
    output_path.write_text(code, encoding="utf-8")
    return resolved_name, output_path, code
