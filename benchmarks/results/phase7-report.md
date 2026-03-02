# Phase 7 Performance Report

Generated at: 2026-03-02T20:09:20.408212+00:00
Python: 3.13.5
Platform: Linux-6.12.57+deb13-amd64-x86_64-with-glibc2.41
Schema: `benchmarks/schemas/phase7-benchmark.xml`

| Scenario | ns/op | msg/s | elapsed ms |
|---|---:|---:|---:|
| decode_only | 16236.7 | 61,588.9 | 113.7 |
| encode_only | 18802.7 | 53,183.8 | 112.8 |
| group_heavy | 114081.6 | 8,765.7 | 228.2 |
| round_trip | 34367.4 | 29,097.3 | 171.8 |
| vardata_heavy | 32411.7 | 30,853.1 | 81.0 |

Regression guardrail:
- `python scripts/check_perf_regression.py --baseline benchmarks/results/baseline.json --current benchmarks/results/latest.json --max-regression-factor 1.35`
