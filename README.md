# pysbe

`pysbe` is a Python implementation of Simple Binary Encoding (SBE) focused on:

- idiomatic Python APIs,
- high performance via flyweight access patterns,
- strong NumPy interoperability.

This repository currently contains **Phase 0-2 foundations**:

- package structure,
- CLI entry points,
- parser + validation model,
- IR model, generator, and traversal helpers,
- fixture management utilities,
- lint/test/type-check tooling.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .[dev]
```

## Commands

```bash
# run tests
python -m pytest

# lint
python -m ruff check .

# type-check
python -m mypy src

# cli help
python -m pysbe --help
```

## CLI (Phase 0)

```bash
python -m pysbe generate schema.xml -o generated/
python -m pysbe generate-ir schema.xml
python -m pysbe fixtures init
python -m pysbe fixtures list
python -m pysbe fixtures import-schema path/to/schema.xml
python -m pysbe fixtures import-java path/to/fixture.bin
```
