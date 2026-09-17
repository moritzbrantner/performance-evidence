#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
VALID_FIXTURES = ROOT / "fixtures" / "valid"
INVALID_FIXTURES = ROOT / "fixtures" / "invalid"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts
    )


def semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    measurements = document.get("measurements", {})
    seen: dict[str, str] = {}
    total = 0

    for group in MEASUREMENT_GROUPS:
        entries = measurements.get(group, [])
        for index, measurement in enumerate(entries):
            total += 1
            name = measurement.get("name")
            if not isinstance(name, str):
                continue

            location = f"measurements.{group}[{index}]"
            previous = seen.get(name)
            if previous is not None:
                errors.append(
                    f"{location}.name duplicates {name!r}; first declared at {previous}.name"
                )
            else:
                seen[name] = location

    if total == 0:
        errors.append("measurements must contain at least one measurement")

    return errors


def validation_errors(
    validator: Draft202012Validator, document: dict[str, Any]
) -> list[str]:
    schema_errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors = [
        f"{format_path(list(error.absolute_path))}: {error.message}"
        for error in schema_errors
    ]
    errors.extend(semantic_errors(document))
    return errors


def validate_fixtures() -> int:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    failures: list[str] = []

    valid_paths = sorted(VALID_FIXTURES.glob("*.json"))
    invalid_paths = sorted(INVALID_FIXTURES.glob("*.json"))

    if not valid_paths:
        failures.append("no valid fixtures found")
    if not invalid_paths:
        failures.append("no invalid fixtures found")

    for path in valid_paths:
        errors = validation_errors(validator, load_json(path))
        if errors:
            failures.append(
                f"valid fixture {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    for path in invalid_paths:
        errors = validation_errors(validator, load_json(path))
        if not errors:
            failures.append(
                f"invalid fixture {path.relative_to(ROOT)} unexpectedly passed validation"
            )

    if failures:
        print("Performance Evidence contract validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(
        "Performance Evidence contract validation passed "
        f"({len(valid_paths)} valid, {len(invalid_paths)} invalid fixtures)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(validate_fixtures())
