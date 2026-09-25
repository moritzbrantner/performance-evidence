#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from input_snapshot import read_input_snapshot
from output_paths import validate_output_path
from validate_schema import validation_errors, validator_for_schema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
COLLECTOR_NAME = "performance-evidence.rust-callgrind-adapter"
COLLECTOR_VERSION = "1.0.0"
ADAPTER_CONTRACT = "rust-callgrind/v1"
CALLGRIND_MEDIA_TYPE = "application/vnd.valgrind.callgrind"

EVENT_MAPPING: dict[str, tuple[str, str, str]] = {
    "Ir": ("cpu.instructions", "instruction", "counter"),
    "Dr": ("memory.data_reads", "count", "counter"),
    "Dw": ("memory.data_writes", "count", "counter"),
    "I1mr": ("cache.l1_instruction_read_misses", "count", "counter"),
    "D1mr": ("cache.l1_data_read_misses", "count", "counter"),
    "D1mw": ("cache.l1_data_write_misses", "count", "counter"),
    "ILmr": ("cache.last_level_instruction_read_misses", "count", "counter"),
    "DLmr": ("cache.last_level_data_read_misses", "count", "counter"),
    "DLmw": ("cache.last_level_data_write_misses", "count", "counter"),
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_evidence(document: dict[str, Any], label: str) -> None:
    errors = validation_errors(validator_for_schema(SCHEMA_PATH), document)
    if errors:
        raise ValueError(label + " violates canonical Performance Evidence:\n  - " + "\n  - ".join(errors))


def parse_nonnegative_integer(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an integer, got {value!r}") from error
    if parsed < 0:
        raise ValueError(f"{label} must be non-negative")
    return parsed


def parse_callgrind(contents: bytes) -> dict[str, Any]:
    events: list[str] | None = None
    summary_values: list[int] | None = None
    creator: str | None = None
    cache_configuration: list[str] = []
    calls_total = 0
    calls_directives = 0

    for raw_line in contents.decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("creator:"):
            creator = line.split(":", 1)[1].strip() or None
            continue
        if line.startswith("events:"):
            if events is not None:
                raise ValueError("Callgrind input contains multiple events declarations")
            events = line.split(":", 1)[1].split()
            if not events:
                raise ValueError("Callgrind events declaration is empty")
            if len(events) != len(set(events)):
                raise ValueError("Callgrind events declaration contains duplicates")
            continue
        if line.startswith("summary:"):
            if summary_values is not None:
                raise ValueError("Callgrind input contains multiple summary declarations")
            tokens = line.split(":", 1)[1].split()
            summary_values = [
                parse_nonnegative_integer(token, "Callgrind summary value")
                for token in tokens
            ]
            continue
        if line.startswith("desc:"):
            description = " ".join(line.split(":", 1)[1].split())
            if "cache" in description.lower() and description not in cache_configuration:
                cache_configuration.append(description)
            continue

        if re.match(r"^calls\s*=", line):
            calls_match = re.match(r"^calls\s*=\s*(\d+)(?:\s+.*)?$", line)
            if calls_match is None:
                raise ValueError(f"malformed Callgrind calls directive: {line!r}")
            calls_total += parse_nonnegative_integer(
                calls_match.group(1), "Callgrind calls count"
            )
            calls_directives += 1

    if events is None:
        raise ValueError("Callgrind input is missing events declaration")
    if summary_values is None:
        raise ValueError("Callgrind input is missing summary declaration")
    if len(events) != len(summary_values):
        raise ValueError(
            "Callgrind summary/event arity mismatch: "
            f"{len(summary_values)} values for {len(events)} events"
        )

    return {
        "creator": creator,
        "events": events,
        "summary": dict(zip(events, summary_values, strict=True)),
        "cache_configuration": sorted(cache_configuration),
        "calls_total": calls_total,
        "calls_directives": calls_directives,
    }


def measurement(
    name: str,
    value: int,
    unit: str,
    measurement_type: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "measurement_type": measurement_type,
    }


def measurement_names(document: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for group in ("useful_work", "induced_work", "outcomes"):
        for entry in document["measurements"][group]:
            names.add(entry["name"])
    return names


def adapter_measurements(parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    unmapped: list[str] = []

    for event in parsed["events"]:
        mapping = EVENT_MAPPING.get(event)
        if mapping is None:
            unmapped.append(event)
            continue
        name, unit, measurement_type = mapping
        result.append(
            measurement(
                name,
                parsed["summary"][event],
                unit,
                measurement_type,
            )
        )

    if parsed["calls_directives"] > 0:
        result.append(
            measurement(
                "cpu.calls",
                parsed["calls_total"],
                "count",
                "counter",
            )
        )

    if not result:
        raise ValueError("Callgrind input contains no supported measurements")
    return result, unmapped


def adapter_environment(
    environment: dict[str, Any],
    parsed: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(environment)
    original_collector = result.get("collector")

    toolchain = dict(result.get("toolchain", {}))
    if parsed["creator"] is not None:
        toolchain["callgrind"] = parsed["creator"]
    if isinstance(original_collector, dict):
        name = original_collector.get("name")
        version = original_collector.get("version")
        if isinstance(name, str) and isinstance(version, str):
            toolchain["upstream_collector"] = f"{name}@{version}"
    if toolchain:
        result["toolchain"] = toolchain

    collector = {
        "name": COLLECTOR_NAME,
        "version": COLLECTOR_VERSION,
    }
    result["collector"] = collector
    fingerprint_inputs = {
        "base_fingerprint": environment["fingerprint"],
        "collector": collector,
        "callgrind_creator": parsed["creator"],
        "events": parsed["events"],
    }
    if parsed["cache_configuration"]:
        fingerprint_inputs["cache_configuration"] = parsed["cache_configuration"]
    result["fingerprint"] = sha256_value(fingerprint_inputs)
    return result


def convert(
    base_evidence: dict[str, Any],
    callgrind_path: Path,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    validate_evidence(base_evidence, "base evidence")
    callgrind_snapshot = read_input_snapshot(callgrind_path)
    parsed = parse_callgrind(callgrind_snapshot.contents)
    additions, unmapped_events = adapter_measurements(parsed)

    existing_names = measurement_names(base_evidence)
    collisions = sorted(
        entry["name"] for entry in additions if entry["name"] in existing_names
    )
    if collisions:
        raise ValueError(
            "Callgrind measurements collide with base evidence: "
            + ", ".join(collisions)
        )

    output = copy.deepcopy(base_evidence)
    output["measurements"]["induced_work"].extend(additions)
    output["environment"] = adapter_environment(base_evidence["environment"], parsed)

    raw_artifact_path = artifact_path or callgrind_path.name
    if not raw_artifact_path:
        raise ValueError("Callgrind artifact path must not be empty")
    artifacts = list(output.get("artifacts", []))
    if any(
        artifact.get("kind") == "callgrind"
        or artifact.get("path") == raw_artifact_path
        for artifact in artifacts
    ):
        raise ValueError("base evidence already contains the Callgrind artifact")
    artifacts.append(
        {
            "kind": "callgrind",
            "path": raw_artifact_path,
            "sha256": callgrind_snapshot.sha256,
            "media_type": CALLGRIND_MEDIA_TYPE,
        }
    )
    output["artifacts"] = artifacts

    extensions = dict(output.get("extensions", {}))
    if "rust.callgrind" in extensions:
        raise ValueError("base evidence already defines rust.callgrind extension")
    callgrind_extension = {
        "adapter_contract": ADAPTER_CONTRACT,
        "creator": parsed["creator"],
        "events": parsed["events"],
        "unmapped_events": unmapped_events,
        "calls_directives": parsed["calls_directives"],
    }
    if parsed["cache_configuration"]:
        callgrind_extension["cache_configuration"] = parsed["cache_configuration"]
    extensions["rust.callgrind"] = callgrind_extension
    output["extensions"] = extensions

    validate_evidence(output, "converted evidence")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich canonical Performance Evidence with deterministic "
            "Callgrind instruction/cache/call measurements."
        )
    )
    parser.add_argument("base_evidence", type=Path)
    parser.add_argument("callgrind", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifact-path",
        help=(
            "Portable path stored in the canonical artifact; "
            "defaults to the Callgrind input filename."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_output_path(args.output, (args.base_evidence, args.callgrind))
        base_evidence = load_json_object(args.base_evidence)
        converted = convert(
            base_evidence,
            args.callgrind,
            args.artifact_path,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(converted, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Rust Callgrind conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"Wrote Callgrind Performance Evidence to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
