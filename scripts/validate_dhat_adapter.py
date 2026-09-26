#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from convert_dhat import convert, load_json_object
from schema_validation import validation_errors


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "dhat"
BASE_PATH = ROOT / "fixtures" / "rust-callgrind" / "base-evidence.json"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"


def measurement_map(document: dict) -> dict[str, dict]:
    return {
        entry["name"]: entry
        for entry in document["measurements"]["induced_work"]
    }


def expect_value_error(action, fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {fragment!r}")


def assert_domain_authority(base: dict, actual: dict) -> None:
    if actual["scenario"] != base["scenario"]:
        raise ValueError("DHAT adapter changed scenario/workload authority")
    if actual["source"] != base["source"]:
        raise ValueError("DHAT adapter changed source authority")
    if actual["measurements"]["useful_work"] != base["measurements"]["useful_work"]:
        raise ValueError("DHAT adapter changed useful-work measurements")
    if actual["measurements"]["outcomes"] != base["measurements"]["outcomes"]:
        raise ValueError("DHAT adapter changed outcome measurements")
    prefix = actual["measurements"]["induced_work"][
        : len(base["measurements"]["induced_work"])
    ]
    if prefix != base["measurements"]["induced_work"]:
        raise ValueError("DHAT adapter changed repository-owned induced work")


def assert_canonical(document: dict) -> None:
    schema = load_json_object(SCHEMA_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = validation_errors(validator, document)
    if errors:
        raise ValueError(
            "DHAT output violates canonical contract:\n  - "
            + "\n  - ".join(errors)
        )


def assert_measurements(
    document: dict,
    expected: dict[str, tuple[int, str, str]],
) -> None:
    mapped = measurement_map(document)
    for name, (value, unit, measurement_type) in expected.items():
        entry = mapped.get(name)
        if entry is None:
            raise ValueError(f"missing DHAT measurement {name}")
        if entry != {
            "name": name,
            "value": value,
            "unit": unit,
            "measurement_type": measurement_type,
        }:
            raise ValueError(f"unexpected DHAT measurement {name}: {entry!r}")


def main() -> int:
    try:
        base = load_json_object(BASE_PATH)

        heap = convert(base, FIXTURE_DIR / "heap.json")
        assert_domain_authority(base, heap)
        assert_canonical(heap)
        assert_measurements(
            heap,
            {
                "memory.allocated_bytes": (1500, "byte", "size"),
                "memory.allocations": (15, "count", "counter"),
                "memory.bytes_at_global_peak": (500, "byte", "size"),
                "memory.blocks_at_global_peak": (5, "count", "counter"),
                "memory.bytes_at_end": (100, "byte", "size"),
                "memory.blocks_at_end": (1, "count", "counter"),
                "memory.heap_read_bytes": (3000, "byte", "size"),
                "memory.heap_written_bytes": (2000, "byte", "size"),
            },
        )
        heap_extension = heap["extensions"]["profiler.dhat"]
        if heap_extension["mode"] != "heap":
            raise ValueError("heap fixture lost DHAT mode")
        if heap_extension["unavailable_heap_fields"]:
            raise ValueError("heap fixture unexpectedly reported unavailable fields")

        rust_heap = convert(base, FIXTURE_DIR / "rust-heap.json")
        assert_domain_authority(base, rust_heap)
        assert_canonical(rust_heap)
        assert_measurements(
            rust_heap,
            {
                "memory.allocated_bytes": (1024, "byte", "size"),
                "memory.allocations": (8, "count", "counter"),
                "memory.bytes_at_global_peak": (384, "byte", "size"),
                "memory.blocks_at_global_peak": (3, "count", "counter"),
                "memory.bytes_at_end": (64, "byte", "size"),
                "memory.blocks_at_end": (1, "count", "counter"),
            },
        )
        rust_names = set(measurement_map(rust_heap))
        if "memory.heap_read_bytes" in rust_names or "memory.heap_written_bytes" in rust_names:
            raise ValueError("Rust DHAT missing read/write data was coerced to zero")
        rust_extension = rust_heap["extensions"]["profiler.dhat"]
        if rust_extension["mode"] != "rust-heap":
            raise ValueError("Rust heap fixture lost DHAT mode")
        if rust_extension["unavailable_heap_fields"] != ["rb", "wb"]:
            raise ValueError(
                "Rust heap fixture did not preserve missing access evidence explicitly"
            )

        copied = convert(base, FIXTURE_DIR / "copy.json")
        assert_domain_authority(base, copied)
        assert_canonical(copied)
        assert_measurements(
            copied,
            {
                "memory.bytes_copied": (5120, "byte", "size"),
                "memory.copy_operations": (16, "count", "counter"),
            },
        )
        added_copy_names = set(measurement_map(copied)) - set(measurement_map(base))
        if added_copy_names != {"memory.bytes_copied", "memory.copy_operations"}:
            raise ValueError("copy mode emitted heap-only measurements")
        if copied["extensions"]["profiler.dhat"]["mode"] != "copy":
            raise ValueError("copy fixture lost DHAT mode")

        if heap["environment"]["fingerprint"] == base["environment"]["fingerprint"]:
            raise ValueError("heap adapter did not bind profiler identity into environment")
        if (
            heap["environment"]["fingerprint"]
            == rust_heap["environment"]["fingerprint"]
        ):
            raise ValueError("different DHAT modes share an environment fingerprint")

        collision = copy.deepcopy(base)
        collision["measurements"]["induced_work"].append(
            {
                "name": "memory.allocated_bytes",
                "value": 1,
                "unit": "byte",
                "measurement_type": "size",
            }
        )
        expect_value_error(
            lambda: convert(collision, FIXTURE_DIR / "heap.json"),
            "collide",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)

            unsupported_version = temporary / "version.json"
            unsupported_version.write_text(
                json.dumps(
                    {
                        "dhatFileVersion": 1,
                        "mode": "heap",
                        "pps": [],
                    }
                ),
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, unsupported_version),
                "unsupported DHAT file version",
            )

            unsupported_mode = temporary / "mode.json"
            unsupported_mode.write_text(
                json.dumps(
                    {
                        "dhatFileVersion": 2,
                        "mode": "ad-hoc",
                        "pps": [],
                    }
                ),
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, unsupported_mode),
                "unsupported DHAT mode",
            )

            negative = temporary / "negative.json"
            negative.write_text(
                json.dumps(
                    {
                        "dhatFileVersion": 2,
                        "mode": "copy",
                        "pps": [{"tb": -1, "tbk": 1}],
                    }
                ),
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, negative),
                "non-negative",
            )

            override = convert(
                base,
                FIXTURE_DIR / "heap.json",
                "artifacts/profiling/resting-stack.dhat.json",
            )
            if override["artifacts"][-1]["path"] != (
                "artifacts/profiling/resting-stack.dhat.json"
            ):
                raise ValueError("portable DHAT artifact-path override was not preserved")

    except (OSError, ValueError, json.JSONDecodeError) as error:
        import sys

        print(f"DHAT adapter validation failed: {error}", file=sys.stderr)
        return 1

    print("DHAT allocation/copy adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
