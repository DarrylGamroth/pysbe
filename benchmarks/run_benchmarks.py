from __future__ import annotations

import argparse
import json
import platform
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from pysbe.generate import generate


def load_generated_module(schema_path: Path, module_name: str = "Perf"):
    with tempfile.TemporaryDirectory(prefix="pysbe-bench-") as tmp:
        tmp_dir = Path(tmp)
        artifact = generate(schema_path=schema_path, output_dir=tmp_dir, module_name=module_name)
        spec = spec_from_file_location(module_name, artifact.output_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("failed to import generated module")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def encode_message(
    module,
    buffer: bytearray,
    *,
    leg_count: int,
    tag_count: int,
    text_size: int,
) -> None:
    enc = module.TradeEncoder.wrap_and_apply_header(buffer, 0)
    enc.seqNum_set(123456789)
    enc.qty_set(77)
    enc.price_set(-12345)
    enc.levels_set([1, 2, 3, 4])

    legs = enc.legs_begin(leg_count)
    for i in range(leg_count):
        leg = legs.next()
        leg.px_set(1000 + i)
        tags = leg.tags_begin(tag_count)
        for j in range(tag_count):
            tag = tags.next()
            tag.code_set((i + 1) * 10 + j)
        leg.note_set(f"leg-{i:02d}".ljust(8, "x"))

    enc.text_set("x" * text_size)


def decode_message(module, payload: bytes | bytearray) -> int:
    dec = module.TradeDecoder.wrap(payload, 0)
    checksum = int(dec.seqNum()) + int(dec.qty()) + int(dec.price())
    levels = dec.levels()
    checksum += int(levels[0]) + int(levels[3])

    legs = dec.legs()
    for leg in legs:
        checksum += int(leg.px())
        tags = leg.tags()
        for tag in tags:
            checksum += int(tag.code())
        checksum += len(leg.note_as_str())

    checksum += len(dec.text_as_str())
    return checksum


@dataclass(frozen=True)
class Scenario:
    name: str
    iterations: int
    warmup: int


def run_scenario(fn, scenario: Scenario) -> dict[str, float]:
    for _ in range(scenario.warmup):
        fn()

    start = time.perf_counter_ns()
    for _ in range(scenario.iterations):
        fn()
    end = time.perf_counter_ns()

    elapsed_ns = end - start
    ns_per_op = elapsed_ns / scenario.iterations
    msg_per_sec = 1_000_000_000.0 / ns_per_op
    return {
        "iterations": float(scenario.iterations),
        "elapsed_ms": elapsed_ns / 1_000_000.0,
        "ns_per_op": ns_per_op,
        "msg_per_sec": msg_per_sec,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run pysbe microbenchmarks")
    parser.add_argument(
        "--schema",
        default=str(Path("benchmarks/schemas/phase7-benchmark.xml")),
        help="SBE schema used for benchmark generation",
    )
    parser.add_argument(
        "--out",
        default=str(Path("benchmarks/results/latest.json")),
        help="Path to output JSON benchmark report",
    )
    args = parser.parse_args()

    schema_path = Path(args.schema)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    module = load_generated_module(schema_path)

    base_buffer = bytearray(8192)
    encode_message(module, base_buffer, leg_count=2, tag_count=2, text_size=32)

    scenarios = [
        (
            "encode_only",
            lambda: encode_message(module, base_buffer, leg_count=2, tag_count=2, text_size=32),
            Scenario("encode_only", 6000, 300),
        ),
        (
            "decode_only",
            lambda: decode_message(module, base_buffer),
            Scenario("decode_only", 7000, 300),
        ),
        (
            "round_trip",
            lambda: (
                encode_message(module, base_buffer, leg_count=2, tag_count=2, text_size=32),
                decode_message(module, base_buffer),
            ),
            Scenario("round_trip", 5000, 300),
        ),
        (
            "group_heavy",
            lambda: (
                encode_message(module, base_buffer, leg_count=8, tag_count=4, text_size=64),
                decode_message(module, base_buffer),
            ),
            Scenario("group_heavy", 2000, 150),
        ),
        (
            "vardata_heavy",
            lambda: (
                encode_message(module, base_buffer, leg_count=2, tag_count=1, text_size=200),
                decode_message(module, base_buffer),
            ),
            Scenario("vardata_heavy", 2500, 150),
        ),
    ]

    results: dict[str, dict[str, float]] = {}
    for name, fn, scenario in scenarios:
        results[name] = run_scenario(fn, scenario)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "machine": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "schema": str(schema_path),
        "results": results,
    }

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
