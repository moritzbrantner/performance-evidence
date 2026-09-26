#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from output_paths import validate_output_path, write_text_atomic
from validate_schema import load_json, validation_errors, validator_for_schema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
ADAPTER_CONTRACT = "application-counters/v1"
FRAGMENT_GROUPS = ("useful_work", "induced_work", "outcomes")
ARTIFACT_MEDIA_TYPE = "application/json"


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


@cache
def canonical_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


def validate_evidence(document: dict[str, Any], label: str) -> None:
    errors = validation_errors(validator_for_schema(SCHEMA_PATH), document)
    if errors:
        raise ValueError(
            label
            + " violates canonical Performance Evidence:\n  - "
            + "\n  - ".join(errors)
        )


def validate_fragment(fragment: dict[str, Any]) -> int:
    unknown = sorted(set(fragment) - set(FRAGMENT_GROUPS))
    if unknown:
        raise ValueError(
            "application counter fragment contains unsupported fields: "
            + ", ".join(unknown)
        )

    schema = canonical_schema()
    measurement_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        **schema["$defs"]["measurement"],
    }
    Draft202012Validator.check_schema(measurement_schema)
    validator = Draft202012Validator(
        measurement_schema,
        format_checker=FormatChecker(),
    )

    seen: dict[str, str] = {}
    count = 0
    for group in FRAGMENT_GROUPS:
        entries = fragment.get(group, [])
        if not isinstance(entries, list):
            raise ValueError(f"application counter fragment {group} must be an array")
        for index, entry in enumerate(entries):
            errors = sorted(
                validator.iter_errors(entry),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if errors:
                detail = "; ".join(error.message for error in errors)
                raise ValueError(
                    f"application counter fragment {group}[{index}] is invalid: {detail}"
                )
            name = entry["name"]
            previous = seen.get(name)
            if previous is not None:
                raise ValueError(
                    f"application counter {name!r} duplicates {previous}"
                )
            seen[name] = f"{group}[{index}]"
            count += 1
    return count


def evidence_measurement_names(document: dict[str, Any]) -> set[str]:
    return {
        entry["name"]
        for group in FRAGMENT_GROUPS
        for entry in document["measurements"][group]
    }


def merge(
    base_evidence: dict[str, Any],
    fragment: dict[str, Any],
    fragment_bytes: bytes,
    artifact_path: str,
) -> dict[str, Any]:
    validate_evidence(base_evidence, "base evidence")
    counter_count = validate_fragment(fragment)

    if counter_count == 0:
        return copy.deepcopy(base_evidence)

    existing_names = evidence_measurement_names(base_evidence)
    fragment_names = {
        entry["name"]
        for group in FRAGMENT_GROUPS
        for entry in fragment.get(group, [])
    }
    collisions = sorted(existing_names & fragment_names)
    if collisions:
        raise ValueError(
            "application counters collide with base evidence: "
            + ", ".join(collisions)
        )

    if not artifact_path:
        raise ValueError("application counter artifact path must not be empty")

    output = copy.deepcopy(base_evidence)
    for group in FRAGMENT_GROUPS:
        output["measurements"][group].extend(
            copy.deepcopy(fragment.get(group, []))
        )

    artifacts = list(output.get("artifacts", []))
    if any(
        artifact.get("kind") == "application-counters"
        or artifact.get("path") == artifact_path
        for artifact in artifacts
    ):
        raise ValueError(
            "base evidence already contains the application counter artifact"
        )
    artifacts.append(
        {
            "kind": "application-counters",
            "path": artifact_path,
            "sha256": sha256_bytes(fragment_bytes),
            "media_type": ARTIFACT_MEDIA_TYPE,
        }
    )
    output["artifacts"] = artifacts

    extensions = dict(output.get("extensions", {}))
    if "application.counters" in extensions:
        raise ValueError(
            "base evidence already defines application.counters extension"
        )
    extensions["application.counters"] = {
        "adapter_contract": ADAPTER_CONTRACT,
        "counter_count": counter_count,
        "groups": [
            group
            for group in FRAGMENT_GROUPS
            if fragment.get(group, [])
        ],
    }
    output["extensions"] = extensions

    validate_evidence(output, "merged evidence")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge repository-owned semantic counters into canonical "
            "Performance Evidence without introducing a parallel counter schema."
        )
    )
    parser.add_argument("base_evidence", type=Path)
    parser.add_argument("counters", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifact-path",
        help=(
            "Portable path stored in the canonical artifact; "
            "defaults to the counter fragment filename."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_output_path(args.output, (args.base_evidence, args.counters))
        base = load_json_object(args.base_evidence)
        fragment_bytes = args.counters.read_bytes()
        fragment = json.loads(fragment_bytes)
        if not isinstance(fragment, dict):
            raise ValueError("application counter fragment root must be an object")
        portable_path = args.artifact_path or args.counters.name
        merged = merge(
            base,
            fragment,
            fragment_bytes,
            portable_path,
        )
        write_text_atomic(
            args.output,
            json.dumps(merged, indent=2, sort_keys=True) + "\n",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Application counter merge failed: {error}", file=sys.stderr)
        return 1

    print(f"Wrote application-counter Performance Evidence to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
