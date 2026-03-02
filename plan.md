# pysbe Implementation Plan

## Goal
Build an idiomatic, high-performance Python Simple Binary Encoding package with first-class NumPy support, using:
- `../simple-binary-encoding` as the wire-format and behavior reference.
- `../SBE.jl` as the architecture and testing baseline (`XML -> IR -> codegen -> flyweight runtime`).

## Scope and Success Criteria

### In scope
- Parse SBE XML schemas and validate key constraints.
- Generate Python codecs from schema IR.
- Flyweight encoders/decoders over existing buffers (no object graph materialization in hot paths).
- Full support for primitives, enums, bitsets, composites, repeating groups, var-data, schema versioning, and byte order.
- Strong NumPy interop for zero-copy fixed arrays and buffer-backed operations.

### Out of scope for v1
- Handwritten/manual codec authoring as a primary workflow.
- Re-implementing every optional tool feature from Java on day one (keep extension points).

### v1 acceptance
- Baseline and extension car schemas round-trip correctly.
- Cross-language parity against Java fixtures for encode and decode.
- Fixed-length primitive arrays exposed as zero-copy NumPy views.
- Repeating-group iteration and var-data traversal are correct and benchmarked.
- Public API and CLI are stable and documented.

## Architecture (Reference-Aligned)

Adopt the same pipeline used by the reference toolchain and your Julia implementation:

1. Parse XML schema -> validated schema model.
2. Convert schema model -> IR token stream (reference-compatible semantics).
3. Generate Python source modules from IR.
4. Use a minimal runtime library for flyweight operations and buffer primitives.

Rationale:
- Keeps parity work localized to parser + IR semantics.
- Makes codegen deterministic and testable.
- Preserves high performance by specializing generated code per schema.

## Package Layout

```text
pysbe/
  pyproject.toml
  src/pysbe/
    __init__.py
    cli.py
    parser/
      xml_parser.py
      validation.py
    ir/
      model.py
      generator.py
      traversal.py
    runtime/
      buffer.py
      primitives.py
      flyweight.py
      group.py
      vardata.py
      enums.py
      errors.py
    codegen/
      emitter.py
      naming.py
      templates.py
      generate.py
  tests/
    unit/
    integration/
    fixtures/
    perf/
```

## API Design (Pythonic + Fast)

### Generation API
- `pysbe.generate(schema_path, output_dir, module_name=None, validate=True, warnings_fatal=False, suppress_warnings=False)`
- `pysbe.generate_ir_file(schema_path, ...)`
- CLI: `python -m pysbe generate schema.xml -o generated/`

### Runtime API shape
- Class-based encoder/decoder flyweights per message:
  - `CarEncoder.wrap_and_apply_header(buffer, offset=0)`
  - `CarDecoder.wrap(buffer, offset=0, acting_block_length=None, acting_version=None)`
- Explicit getter/setter methods (`serial_number()`, `serial_number_set(v)` or `get_/set_` convention chosen once and kept consistent).
- Group APIs mirror SBE semantics with explicit `next()` and iterator support.
- Var-data APIs return `memoryview` by default; optional typed conversions (`as_str()`, `as_numpy()`).

### NumPy integration contract
- Accept any writable buffer-protocol object; optimize for:
  - `numpy.ndarray` of `uint8`, C-contiguous.
  - `bytearray`, `memoryview`, `mmap`.
- Fixed primitive arrays decode to zero-copy `np.ndarray` views with correct endianness.
- Provide helpers:
  - `to_numpy_uint8(buffer)` for safe adaptation.
  - `shares_memory` assertions in tests for no-copy guarantees.

## Performance Strategy

### Core principles
- Never slice-copy in hot paths; only create views.
- Cache format/dtype metadata per generated module.
- Keep access-order checks optional (debug mode), off by default.
- Avoid per-field dynamic dispatch in generated accessors.

### Runtime implementation choices
- Scalars: use `struct.Struct(...).pack_into/unpack_from` cached per type + endianness.
- Arrays: use `np.frombuffer`/`ndarray` view with computed dtype (`newbyteorder` as needed).
- Shared position pointer object for groups/var-data traversal.
- Precompute field offsets, block lengths, and token boundaries at codegen time.

### Perf gates (relative and observable)
- No-copy fixed-array decode (`np.shares_memory == True`).
- No-copy var-data raw bytes access (`memoryview` over backing buffer).
- Benchmark suite tracks:
  - encode-only
  - decode-only
  - round-trip
  - group-heavy and var-data-heavy messages
- Regressions fail CI when throughput drops or allocations/copies increase materially.

## Implementation Phases

## Phase 0: Project Bootstrap
- Create package skeleton, tooling, lint/test/typing setup.
- Add CLI scaffold and generation entry points.
- Add fixture management utilities (schema files + generated Java binaries).

Exit criteria:
- `pytest` and lint pass on empty/minimal scaffolding.
- CLI command resolves and prints help.

## Phase 1: XML Parser + Validation
- Port key parsing/validation behavior from reference + SBE.jl:
  - type/message discovery
  - duplicate ids/names
  - field ordering constraints
  - header type and basic schema checks
  - warning policy (`warnings_fatal`, `suppress_warnings`)
- Build schema model sufficient for IR generation.

Exit criteria:
- Parser unit tests pass on baseline schema and selected negative schemas.

## Phase 2: IR Model + IR Generator
- Implement IR classes (`Signal`, `Presence`, primitive metadata, tokens, encodings, schema IR container).
- Generate message/header/type token streams matching reference semantics.
- Add traversal helpers (`collect_fields/groups/var_data`, end-signal detection).

Exit criteria:
- IR signatures for representative schemas match expected token properties.
- Token stream parity tests against selected Java IR fixtures.

## Phase 3: Runtime Core (No Codegen Yet)
- Implement buffer abstraction and primitive read/write helpers.
- Implement base flyweight classes for message/composite/group/var-data.
- Implement shared position tracking and bounds checks.
- Implement NumPy adapters and zero-copy view helpers.

Exit criteria:
- Runtime unit tests validate scalar/array read-write for LE/BE.
- Zero-copy invariants proven with `np.shares_memory`.

## Phase 4: Codegen MVP (Baseline Message Support)
- Generate codecs for:
  - message header
  - primitive scalar fields
  - fixed primitive arrays
  - fixed char arrays
  - enums and bitsets
  - composites without nested groups
- Emit importable Python modules and stable names (keyword sanitization for Python).

Exit criteria:
- Generated code for simple/baseline schema imports and round-trips.
- Golden-file smoke tests pass.

## Phase 5: Full SBE Features
- Repeating groups (including nested groups).
- Var-data fields with length-prefix handling.
- Version gating (`sinceVersion`, acting version/block length).
- Constant/optional/null/min/max semantics.
- Endianness per schema.

Exit criteria:
- Baseline + extension schema parity tests pass.
- Complex nested schema tests pass (ported from SBE.jl coverage set).

## Phase 6: Cross-Language Compatibility
- Add Java fixture generation + verification workflow:
  - decode Java-produced binaries in Python
  - encode in Python and verify from Java helper
- Reuse schemas and fixture patterns from `../SBE.jl/test`.

Exit criteria:
- Deterministic fixture parity in CI.
- Compatibility report for covered schemas/features.

## Phase 7: Performance Hardening
- Benchmark harness (`pytest-benchmark` or `asv`) with stable scenarios.
- Profile hot paths (`py-spy`, `perf`, `cProfile`) and remove avoidable overhead.
- Optional accelerated backend investigation (Cython/Rust extension) only if needed after pure-Python + NumPy tuning.

Exit criteria:
- Performance report checked in.
- CI guardrails for benchmark regressions and copy/allocation regressions.

## Testing Matrix

### Correctness
- Unit tests:
  - primitive bounds/nulls
  - enum/set semantics
  - endian correctness
  - position management
- Integration tests:
  - baseline car
  - extension car
  - nested groups
  - var-data-heavy messages
  - versioned schema behavior

### Interop
- Java fixtures from reference tool.
- Optional parity with `SBE.jl` encoded samples for additional confidence.

### Robustness
- Negative schema tests (invalid offsets, duplicate ids, invalid refs).
- Property tests for random valid field values (Hypothesis).

## Risks and Mitigations
- Risk: Python overhead in tight loops.
  - Mitigation: generated direct methods, cached structs, zero-copy views, profile-guided tuning.
- Risk: NumPy endianness subtleties causing hidden copies.
  - Mitigation: explicit dtype byte-order handling and memory-sharing tests.
- Risk: Feature drift from reference semantics.
  - Mitigation: IR/token parity tests and fixture-based interop checks.

## Immediate Next Steps (Execution Order)
1. Set up package skeleton, tooling, and CLI scaffold (Phase 0).
2. Implement parser + validation subset with baseline schemas (Phase 1).
3. Implement IR model/generator + parity tests (Phase 2).
4. Implement runtime primitive/buffer layer with NumPy zero-copy tests (Phase 3).

