#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from convert_agent_loop_efficiency import convert_report
from validate_schema import validation_errors


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "agent-loop-efficiency"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
EXPECTED_NAME = "018f5d43-4d1c-7fd5-aed5-d451fd71c110.attempt-1.performance-evidence.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    try:
        report = load_json(FIXTURE_DIR / "report.json")
        expected = load_json(FIXTURE_DIR / "expected.json")
        converted = convert_report(report, source_dirty=False)
        if len(converted) != 1:
            raise ValueError(f"expected one converted attempt, got {len(converted)}")
        name, actual = converted[0]
        if name != EXPECTED_NAME:
            raise ValueError(f"unexpected output name: {name}")
        if actual != expected:
            print("Agent-loop adapter fixture mismatch.", file=sys.stderr)
            print(
                json.dumps(
                    {"expected": expected, "actual": actual}, indent=2, sort_keys=True
                ),
                file=sys.stderr,
            )
            return 1

        schema = load_json(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = validation_errors(validator, actual)
        if errors:
            print("Converted agent-loop evidence violates canonical contract:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Agent-loop adapter validation failed: {error}", file=sys.stderr)
        return 1

    print("Agent-loop efficiency adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
