#!/usr/bin/env python3

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")


def reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid non-finite JSON number {value!r}")


def load_json_bytes(contents: bytes) -> Any:
    return json.loads(contents.decode("utf-8"), parse_constant=reject_json_constant)


def load_json(path: Path) -> Any:
    return load_json_bytes(path.read_bytes())


@cache
def validator_for_schema(path: Path) -> Draft202012Validator:
    schema = load_json(path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts
    )


def portable_artifact_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if len(parts[0]) == 2 and parts[0][0].isalpha() and parts[0][1] == ":":
        return False
    return True


def semantic_errors(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []

    errors: list[str] = []
    measurements = document.get("measurements")
    if isinstance(measurements, dict):
        seen: dict[str, str] = {}
        total = 0

        for group in MEASUREMENT_GROUPS:
            entries = measurements.get(group)
            if not isinstance(entries, list):
                continue
            for index, measurement in enumerate(entries):
                total += 1
                if not isinstance(measurement, dict):
                    continue
                name = measurement.get("name")
                if not isinstance(name, str):
                    continue

                location = f"measurements.{group}[{index}]"
                previous = seen.get(name)
                if previous is not None:
                    errors.append(
                        f"{location}.name duplicates {name!r}; "
                        f"first declared at {previous}.name"
                    )
                else:
                    seen[name] = location

                value = measurement.get("value")
                if isinstance(value, float) and not math.isfinite(value):
                    errors.append(f"{location}.value must be finite")

        if total == 0:
            errors.append("measurements must contain at least one measurement")

    artifacts = document.get("artifacts")
    if isinstance(artifacts, list):
        seen_paths: dict[str, int] = {}
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                continue
            path = artifact.get("path")
            if not isinstance(path, str):
                continue
            if not portable_artifact_path(path):
                errors.append(
                    f"artifacts[{index}].path must be a portable relative POSIX path"
                )
            previous = seen_paths.get(path)
            if previous is not None:
                errors.append(
                    f"artifacts[{index}].path duplicates artifacts[{previous}].path"
                )
            else:
                seen_paths[path] = index

    return errors


def validation_errors(
    validator: Draft202012Validator,
    document: Any,
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
