from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare benchmark result against baseline")
    parser.add_argument("--baseline", default="benchmarks/results/baseline.json")
    parser.add_argument("--current", default="benchmarks/results/latest.json")
    parser.add_argument(
        "--max-regression-factor",
        type=float,
        default=1.35,
        help="Fail if ns_per_op exceeds baseline * factor",
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    current_path = Path(args.current)

    if not baseline_path.is_file():
        print(f"baseline missing: {baseline_path}")
        return 2
    if not current_path.is_file():
        print(f"current report missing: {current_path}")
        return 2

    baseline = load_report(baseline_path).get("results", {})
    current = load_report(current_path).get("results", {})

    failed = False
    for scenario, baseline_metrics in sorted(baseline.items()):
        if scenario not in current:
            print(f"missing scenario in current report: {scenario}")
            failed = True
            continue
        baseline_ns = float(baseline_metrics["ns_per_op"])
        current_ns = float(current[scenario]["ns_per_op"])
        allowed = baseline_ns * args.max_regression_factor
        ratio = current_ns / baseline_ns if baseline_ns else 0.0
        print(
            f"{scenario}: baseline={baseline_ns:.1f}ns current={current_ns:.1f}ns "
            f"ratio={ratio:.3f} allowed={allowed:.1f}"
        )
        if current_ns > allowed:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
