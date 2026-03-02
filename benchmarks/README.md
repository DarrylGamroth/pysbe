# Benchmarks

Phase 7 benchmark harness for pysbe codegen/runtime.

## Run Benchmarks

```bash
source .venv/bin/activate
python benchmarks/run_benchmarks.py
```

Writes `benchmarks/results/latest.json`.

## Check Regressions

```bash
source .venv/bin/activate
python scripts/check_perf_regression.py \
  --baseline benchmarks/results/baseline.json \
  --current benchmarks/results/latest.json \
  --max-regression-factor 1.35
```

Exit codes:
- `0`: pass
- `1`: regression detected
- `2`: missing report/baseline

## CI Guardrail Suggestion

Use the two commands above in CI and fail build on non-zero from `check_perf_regression.py`.
