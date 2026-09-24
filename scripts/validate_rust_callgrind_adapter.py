#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

from convert_rust_callgrind import convert, load_json_object
from validate_schema import validation_errors

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "rust-callgrind"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"


def expect_value_error(action, expected_fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if expected_fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {expected_fragment!r}")


def main() -> int:
    try:
        base = load_json_object(FIXTURE_DIR / "base-evidence.json")
        expected = load_json_object(FIXTURE_DIR / "expected.json")
        callgrind_path = FIXTURE_DIR / "callgrind.out"

        actual = convert(base, callgrind_path)
        if actual != expected:
            raise ValueError(
                "Rust Callgrind fixture mismatch:\n"
                + json.dumps(
                    {"expected": expected, "actual": actual},
                    indent=2,
                    sort_keys=True,
                )
            )

        for group in ("useful_work", "outcomes"):
            if actual["measurements"][group] != base["measurements"][group]:
                raise ValueError(f"adapter changed domain-owned {group} measurements")
        if (
            actual["measurements"]["induced_work"][: len(base["measurements"]["induced_work"])]
            != base["measurements"]["induced_work"]
        ):
            raise ValueError("adapter changed domain-owned induced-work measurements")

        schema = load_json_object(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = validation_errors(validator, actual)
        if errors:
            raise ValueError(
                "converted Callgrind evidence violates canonical contract:\n  - "
                + "\n  - ".join(errors)
            )

        collision = copy.deepcopy(base)
        collision["measurements"]["induced_work"].append(
            {
                "name": "cpu.instructions",
                "value": 1,
                "unit": "instruction",
                "measurement_type": "counter",
            }
        )
        expect_value_error(
            lambda: convert(collision, callgrind_path),
            "collide",
        )

        extension_collision = copy.deepcopy(base)
        extension_collision["extensions"] = {
            "rust.callgrind": {"owner": "repository"}
        }
        expect_value_error(
            lambda: convert(extension_collision, callgrind_path),
            "already defines rust.callgrind",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)

            missing_summary = temporary / "missing-summary.out"
            missing_summary.write_text(
                "events: Ir Dr\n",
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, missing_summary),
                "missing summary",
            )

            mismatched = temporary / "mismatched.out"
            mismatched.write_text(
                "events: Ir Dr\nsummary: 1\n",
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, mismatched),
                "arity mismatch",
            )

            unsupported = temporary / "unsupported.out"
            unsupported.write_text(
                "events: Bc\nsummary: 3\n",
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, unsupported),
                "no supported measurements",
            )

            whitespace_calls = temporary / "whitespace-calls.out"
            whitespace_calls.write_text(
                "events: Ir\nsummary: 1\ncalls = 5 0\ncalls= 7 0\n",
                encoding="utf-8",
            )
            whitespace_result = convert(base, whitespace_calls)
            cpu_calls = next(
                entry
                for entry in whitespace_result["measurements"]["induced_work"]
                if entry["name"] == "cpu.calls"
            )
            if cpu_calls["value"] != 12:
                raise ValueError("Callgrind calls directives with whitespace were undercounted")

            malformed_calls = temporary / "malformed-calls.out"
            malformed_calls.write_text(
                "events: Ir\nsummary: 1\ncalls = nope 0\n",
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, malformed_calls),
                "malformed Callgrind calls directive",
            )

            cache_a = temporary / "cache-a.out"
            cache_b = temporary / "cache-b.out"
            cache_a.write_text(
                "creator: callgrind-3.22.0\n"
                "desc: D1 cache: 32768 B, 64 B, 8-way associative\n"
                "events: Ir\nsummary: 1\n",
                encoding="utf-8",
            )
            cache_b.write_text(
                "creator: callgrind-3.22.0\n"
                "desc: D1 cache: 65536 B, 64 B, 8-way associative\n"
                "events: Ir\nsummary: 1\n",
                encoding="utf-8",
            )
            cache_a_result = convert(base, cache_a)
            cache_b_result = convert(base, cache_b)
            if (
                cache_a_result["environment"]["fingerprint"]
                == cache_b_result["environment"]["fingerprint"]
            ):
                raise ValueError("Callgrind cache configuration did not affect environment identity")
            if cache_a_result["extensions"]["rust.callgrind"].get("cache_configuration") != [
                "D1 cache: 32768 B, 64 B, 8-way associative"
            ]:
                raise ValueError("Callgrind cache configuration was not preserved")

            override = convert(
                base,
                callgrind_path,
                "artifacts/profiling/resting-stack.callgrind",
            )
            if override["artifacts"][-1]["path"] != (
                "artifacts/profiling/resting-stack.callgrind"
            ):
                raise ValueError("portable artifact-path override was not preserved")

    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Rust Callgrind adapter validation failed: {error}", file=sys.stderr)
        return 1

    print("Rust Callgrind adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
