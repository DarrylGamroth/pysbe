"""Command-line interface for pysbe."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pysbe.fixtures import (
    ensure_fixture_layout,
    import_java_fixture,
    import_schema_fixture,
    list_fixtures,
    sync_fixture_manifest,
)
from pysbe.generate import generate, generate_ir_file


def _cmd_generate(args: argparse.Namespace) -> int:
    artifact = generate(
        schema_path=args.schema,
        output_dir=args.output_dir,
        module_name=args.module_name,
        overwrite=args.overwrite,
    )
    print(artifact.output_path)
    return 0


def _cmd_generate_ir(args: argparse.Namespace) -> int:
    ir = generate_ir_file(args.schema)
    payload = json.dumps(ir, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
        print(output_path)
    else:
        print(payload)
    return 0


def _cmd_fixtures_init(args: argparse.Namespace) -> int:
    del args
    ensure_fixture_layout()
    manifest = sync_fixture_manifest()
    print(manifest)
    return 0


def _cmd_fixtures_list(args: argparse.Namespace) -> int:
    del args
    print(json.dumps(list_fixtures(), indent=2, sort_keys=True))
    return 0


def _cmd_fixtures_import_schema(args: argparse.Namespace) -> int:
    path = import_schema_fixture(args.source, name=args.name)
    print(path)
    return 0


def _cmd_fixtures_import_java(args: argparse.Namespace) -> int:
    path = import_java_fixture(args.source, name=args.name)
    print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pysbe", description="Python SBE tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="Generate Python module(s) from an SBE schema"
    )
    generate_parser.add_argument("schema", help="Path to SBE schema XML")
    generate_parser.add_argument(
        "-o", "--output-dir", default="generated", help="Output directory for generated module(s)"
    )
    generate_parser.add_argument("-m", "--module-name", help="Override generated module name")
    generate_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs",
    )
    generate_parser.set_defaults(func=_cmd_generate)

    ir_parser = subparsers.add_parser("generate-ir", help="Emit minimal schema metadata JSON")
    ir_parser.add_argument("schema", help="Path to SBE schema XML")
    ir_parser.add_argument("-o", "--output", help="Write JSON output to a file instead of stdout")
    ir_parser.set_defaults(func=_cmd_generate_ir)

    fixtures_parser = subparsers.add_parser("fixtures", help="Manage local test fixtures")
    fixtures_subparsers = fixtures_parser.add_subparsers(dest="fixtures_command", required=True)

    fixtures_init = fixtures_subparsers.add_parser(
        "init",
        help="Create fixture directories and manifest",
    )
    fixtures_init.set_defaults(func=_cmd_fixtures_init)

    fixtures_list = fixtures_subparsers.add_parser("list", help="List registered fixtures")
    fixtures_list.set_defaults(func=_cmd_fixtures_list)

    fixtures_import_schema = fixtures_subparsers.add_parser(
        "import-schema", help="Copy a schema fixture into tests/fixtures/schemas"
    )
    fixtures_import_schema.add_argument("source", help="Source schema file path")
    fixtures_import_schema.add_argument("--name", help="Optional destination file name")
    fixtures_import_schema.set_defaults(func=_cmd_fixtures_import_schema)

    fixtures_import_java = fixtures_subparsers.add_parser(
        "import-java", help="Copy a Java binary fixture into tests/fixtures/java"
    )
    fixtures_import_java.add_argument("source", help="Source binary fixture path")
    fixtures_import_java.add_argument("--name", help="Optional destination file name")
    fixtures_import_java.set_defaults(func=_cmd_fixtures_import_java)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = args.func
    if not callable(func):
        raise TypeError("CLI handler is not callable")
    command_func: Callable[[argparse.Namespace], int] = func
    return command_func(args)


def entrypoint() -> int:
    return main()
