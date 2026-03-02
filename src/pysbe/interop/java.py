"""Java reference interop workflow for fixture parity checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pysbe.parser import SchemaDef, TypeDef, parse_schema

DEFAULT_JAVA_INTEROP_VALUES: dict[str, int | float] = {
    "seqNum": 9001,
    "qty": 77,
    "price": -1234,
}


class JavaInteropUnavailable(RuntimeError):
    """Raised when Java interop prerequisites are missing."""


@dataclass(frozen=True)
class JavaPrerequisites:
    """Resolved Java tooling and SBE jar locations."""

    java: str
    javac: str
    jar_path: Path
    ref_dir: Path | None


def _default_ref_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "simple-binary-encoding"


def _find_sbe_jar(ref_dir: Path) -> Path | None:
    env_jar = os.environ.get("SBE_JAR_PATH")
    if env_jar:
        path = Path(env_jar)
        if path.is_file():
            return path

    patterns = [
        ref_dir / "sbe-all" / "build" / "libs",
        ref_dir / "build" / "libs",
    ]
    for directory in patterns:
        if not directory.is_dir():
            continue
        jars = sorted(directory.glob("sbe-all-*.jar"))
        if jars:
            return jars[-1]
    return None


def find_java_prerequisites(ref_dir: str | Path | None = None) -> JavaPrerequisites | None:
    """Detect Java/Javac and SBE all-in-one jar."""

    java = shutil.which("java")
    javac = shutil.which("javac")
    if java is None or javac is None:
        return None

    resolved_ref_dir = Path(ref_dir) if ref_dir is not None else _default_ref_dir()
    search_root = resolved_ref_dir if resolved_ref_dir.is_dir() else Path(".")
    jar_path = _find_sbe_jar(search_root)
    if jar_path is None:
        return None
    ref_dir_value = resolved_ref_dir if resolved_ref_dir.is_dir() else None
    return JavaPrerequisites(java=java, javac=javac, jar_path=jar_path, ref_dir=ref_dir_value)


def _java_literal(value: int | float, primitive_type: str) -> str:
    if primitive_type in {"float"}:
        return f"{float(value)}f"
    if primitive_type in {"double"}:
        return f"{float(value)}d"
    if primitive_type in {"uint64", "int64", "uint32"}:
        return f"{int(value)}L"
    return str(int(value))


def _resolve_primitive_type(schema: SchemaDef, field_type_name: str) -> str:
    type_def: TypeDef = schema.types_by_name[field_type_name]
    if type_def.kind == "primitive":
        return type_def.name
    if type_def.kind in {"type", "enum", "set"} and type_def.primitive_type is not None:
        return type_def.primitive_type
    raise JavaInteropUnavailable(
        f"Java interop currently supports primitive/enum/set fields only, got {type_def.kind!r}"
    )


def _render_java_tool(schema: SchemaDef, values: dict[str, int | float]) -> str:
    message = schema.messages[0]
    package_name = schema.package_name
    message_class = message.name

    encode_lines: list[str] = []
    verify_lines: list[str] = []
    for field in message.fields:
        if field.kind != "field" or field.type_name is None:
            raise JavaInteropUnavailable(
                "Java interop fixture supports only fixed primitive/enum/set fields"
            )
        primitive_type = _resolve_primitive_type(schema, field.type_name)
        value = values.get(field.name)
        if value is None:
            raise JavaInteropUnavailable(
                f"missing interop value for field {field.name!r}; provide via values map"
            )
        literal = _java_literal(value, primitive_type)
        method = field.name
        encode_lines.append(f"        encoder.{method}({literal});")

        if primitive_type == "float":
            verify_lines.append(f"        if (Float.compare(decoder.{method}(), {literal}) != 0)")
        elif primitive_type == "double":
            verify_lines.append(f"        if (Double.compare(decoder.{method}(), {literal}) != 0)")
        else:
            verify_lines.append(f"        if (decoder.{method}() != {literal})")
        verify_lines.append(
            f'        {{ throw new IllegalStateException("field mismatch: {method}"); }}'
        )

    return f"""
import org.agrona.concurrent.UnsafeBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import {package_name}.MessageHeaderDecoder;
import {package_name}.MessageHeaderEncoder;
import {package_name}.{message_class}Decoder;
import {package_name}.{message_class}Encoder;

public final class InteropFixtureTool {{
    private InteropFixtureTool() {{}}

    public static void main(final String[] args) throws Exception {{
        if (args.length != 2) {{
            throw new IllegalArgumentException("usage: <encode|verify> <path>");
        }}

        final String mode = args[0];
        final Path path = Path.of(args[1]);
        if ("encode".equals(mode)) {{
            encode(path);
        }}
        else if ("verify".equals(mode)) {{
            verify(path);
        }}
        else {{
            throw new IllegalArgumentException("unknown mode: " + mode);
        }}
    }}

    private static void encode(final Path path) throws Exception {{
        final byte[] bytes = new byte[1024];
        final UnsafeBuffer buffer = new UnsafeBuffer(bytes);

        final MessageHeaderEncoder header = new MessageHeaderEncoder();
        final {message_class}Encoder encoder = new {message_class}Encoder();
        encoder.wrapAndApplyHeader(buffer, 0, header);
{chr(10).join(encode_lines)}

        final int length = MessageHeaderEncoder.ENCODED_LENGTH + encoder.encodedLength();
        Files.write(path, Arrays.copyOf(bytes, length));
    }}

    private static void verify(final Path path) throws Exception {{
        final byte[] bytes = Files.readAllBytes(path);
        final UnsafeBuffer buffer = new UnsafeBuffer(bytes);

        final MessageHeaderDecoder header = new MessageHeaderDecoder();
        header.wrap(buffer, 0);
        final {message_class}Decoder decoder = new {message_class}Decoder();
        decoder.wrap(
            buffer,
            MessageHeaderDecoder.ENCODED_LENGTH,
            header.blockLength(),
            header.version());
{chr(10).join(verify_lines)}
    }}
}}
""".strip()


def _generate_java_code(prereq: JavaPrerequisites, schema_path: Path, output_dir: Path) -> None:
    cmd = [
        prereq.java,
        "--add-opens=java.base/jdk.internal.misc=ALL-UNNAMED",
        "-Dsbe.target.language=Java",
        f"-Dsbe.output.dir={output_dir}",
        "-jar",
        str(prereq.jar_path),
        str(schema_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _compile_tool(
    prereq: JavaPrerequisites,
    generated_src_dir: Path,
    tool_source_path: Path,
    classes_dir: Path,
) -> str:
    source_files = [str(path) for path in generated_src_dir.rglob("*.java")]
    source_files.append(str(tool_source_path))
    classes_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        prereq.javac,
        "-cp",
        str(prereq.jar_path),
        "-d",
        str(classes_dir),
        *source_files,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return f"{classes_dir}:{prereq.jar_path}"


def _run_tool(prereq: JavaPrerequisites, classpath: str, mode: str, file_path: Path) -> None:
    cmd = [
        prereq.java,
        "--add-opens=java.base/jdk.internal.misc=ALL-UNNAMED",
        "-cp",
        classpath,
        "InteropFixtureTool",
        mode,
        str(file_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def encode_fixture_with_java(
    schema_path: str | Path,
    output_path: str | Path,
    *,
    values: dict[str, int | float] | None = None,
    ref_dir: str | Path | None = None,
) -> Path:
    """Generate a Java-encoded fixture for the schema's first message."""

    prereq = find_java_prerequisites(ref_dir)
    if prereq is None:
        raise JavaInteropUnavailable("java/javac/sbe-all jar not available")
    schema = parse_schema(schema_path)
    if not schema.messages:
        raise JavaInteropUnavailable("schema contains no messages for interop fixture")
    resolved_values = values or DEFAULT_JAVA_INTEROP_VALUES

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pysbe-java-interop-") as tmp:
        tmp_dir = Path(tmp)
        generated = tmp_dir / "generated-java"
        tool_source = tmp_dir / "InteropFixtureTool.java"
        classes_dir = tmp_dir / "classes"

        _generate_java_code(prereq, Path(schema_path), generated)
        tool_source.write_text(_render_java_tool(schema, resolved_values), encoding="utf-8")
        classpath = _compile_tool(prereq, generated, tool_source, classes_dir)
        _run_tool(prereq, classpath, "encode", output)

    return output


def verify_payload_with_java(
    schema_path: str | Path,
    payload_path: str | Path,
    *,
    values: dict[str, int | float] | None = None,
    ref_dir: str | Path | None = None,
) -> None:
    """Verify a Python-encoded payload with Java-generated decoder."""

    prereq = find_java_prerequisites(ref_dir)
    if prereq is None:
        raise JavaInteropUnavailable("java/javac/sbe-all jar not available")
    schema = parse_schema(schema_path)
    if not schema.messages:
        raise JavaInteropUnavailable("schema contains no messages for interop fixture")
    resolved_values = values or DEFAULT_JAVA_INTEROP_VALUES

    payload = Path(payload_path)
    with tempfile.TemporaryDirectory(prefix="pysbe-java-interop-") as tmp:
        tmp_dir = Path(tmp)
        generated = tmp_dir / "generated-java"
        tool_source = tmp_dir / "InteropFixtureTool.java"
        classes_dir = tmp_dir / "classes"

        _generate_java_code(prereq, Path(schema_path), generated)
        tool_source.write_text(_render_java_tool(schema, resolved_values), encoding="utf-8")
        classpath = _compile_tool(prereq, generated, tool_source, classes_dir)
        _run_tool(prereq, classpath, "verify", payload)
