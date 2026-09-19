#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from validate_schema import validation_errors


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
COLLECTOR_NAME = "performance-evidence.dhat-adapter"
COLLECTOR_VERSION = "1.0.0"
ADAPTER_CONTRACT = "dhat/v1"
DHAT_MEDIA_TYPE = "application/json"
SUPPORTED_MODES = {"heap", "rust-heap", "copy"}


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
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = validation_errors(validator, document)
    if errors:
        raise ValueError(
            label
            + " violates canonical Performance Evidence:\n  - "
            + "\n  - ".join(errors)
        )


def nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def parse_dhat(path: Path) -> dict[str, Any]:
    document = load_json_object(path)
    version = nonnegative_integer(document.get("dhatFileVersion"), "dhatFileVersion")
    if version != 2:
        raise ValueError(f"unsupported DHAT file version: {version}")

    mode = document.get("mode")
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            "unsupported DHAT mode: "
            + repr(mode)
            + "; expected heap, rust-heap, or copy"
        )

    pps = document.get("pps")
    if not isinstance(pps, list):
        raise ValueError("DHAT pps must be an array")
    for index, pp in enumerate(pps):
        if not isinstance(pp, dict):
            raise ValueError(f"DHAT pps[{index}] must be an object")
        nonnegative_integer(pp.get("tb"), f"DHAT pps[{index}].tb")
        nonnegative_integer(pp.get("tbk"), f"DHAT pps[{index}].tbk")

    return document


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
    result: set[str] = set()
    for group in ("useful_work", "induced_work", "outcomes"):
        for entry in document["measurements"][group]:
            result.add(entry["name"])
    return result


def required_sum(pps: list[dict[str, Any]], field: str) -> int:
    return sum(
        nonnegative_integer(pp.get(field), f"DHAT {field}")
        for pp in pps
    )


def optional_sum(pps: list[dict[str, Any]], field: str) -> int | None:
    if not pps or any(field not in pp for pp in pps):
        return None
    return sum(
        nonnegative_integer(pp.get(field), f"DHAT {field}")
        for pp in pps
    )


def append_optional(
    target: list[dict[str, Any]],
    name: str,
    value: int | None,
    unit: str,
    measurement_type: str,
) -> None:
    if value is not None:
        target.append(measurement(name, value, unit, measurement_type))


def adapter_measurements(document: dict[str, Any]) -> list[dict[str, Any]]:
    mode = document["mode"]
    pps = document["pps"]
    total_bytes = required_sum(pps, "tb")
    total_blocks = required_sum(pps, "tbk")

    if mode == "copy":
        return [
            measurement("memory.bytes_copied", total_bytes, "byte", "size"),
            measurement("memory.copy_operations", total_blocks, "count", "counter"),
        ]

    result = [
        measurement("memory.allocated_bytes", total_bytes, "byte", "size"),
        measurement("memory.allocations", total_blocks, "count", "counter"),
    ]
    append_optional(
        result,
        "memory.bytes_at_global_peak",
        optional_sum(pps, "gb"),
        "byte",
        "size",
    )
    append_optional(
        result,
        "memory.blocks_at_global_peak",
        optional_sum(pps, "gbk"),
        "count",
        "counter",
    )
    append_optional(
        result,
        "memory.bytes_at_end",
        optional_sum(pps, "eb"),
        "byte",
        "size",
    )
    append_optional(
        result,
        "memory.blocks_at_end",
        optional_sum(pps, "ebk"),
        "count",
        "counter",
    )
    append_optional(
        result,
        "memory.heap_read_bytes",
        optional_sum(pps, "rb"),
        "byte",
        "size",
    )
    append_optional(
        result,
        "memory.heap_written_bytes",
        optional_sum(pps, "wb"),
        "byte",
        "size",
    )
    return result


def adapter_environment(
    environment: dict[str, Any],
    document: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(environment)
    original_collector = result.get("collector")

    toolchain = dict(result.get("toolchain", {}))
    toolchain["dhat"] = (
        f"file-v{document['dhatFileVersion']}:{document['mode']}"
    )
    if isinstance(original_collector, dict):
        name = original_collector.get("name")
        version = original_collector.get("version")
        if isinstance(name, str) and isinstance(version, str):
            toolchain["upstream_collector"] = f"{name}@{version}"
    result["toolchain"] = toolchain

    collector = {
        "name": COLLECTOR_NAME,
        "version": COLLECTOR_VERSION,
    }
    result["collector"] = collector
    result["fingerprint"] = sha256_value(
        {
            "base_fingerprint": environment["fingerprint"],
            "collector": collector,
            "dhat_file_version": document["dhatFileVersion"],
            "mode": document["mode"],
            "time_unit": document.get("tu"),
        }
    )
    return result


def convert(
    base_evidence: dict[str, Any],
    dhat_path: Path,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    validate_evidence(base_evidence, "base evidence")
    dhat = parse_dhat(dhat_path)
    additions = adapter_measurements(dhat)

    existing_names = measurement_names(base_evidence)
    collisions = sorted(
        entry["name"] for entry in additions if entry["name"] in existing_names
    )
    if collisions:
        raise ValueError(
            "DHAT measurements collide with base evidence: "
            + ", ".join(collisions)
        )

    output = copy.deepcopy(base_evidence)
    output["measurements"]["induced_work"].extend(additions)
    output["environment"] = adapter_environment(base_evidence["environment"], dhat)

    portable_path = artifact_path or dhat_path.name
    if not portable_path:
        raise ValueError("DHAT artifact path must not be empty")
    artifacts = list(output.get("artifacts", []))
    if any(
        artifact.get("kind") == "dhat"
        or artifact.get("path") == portable_path
        for artifact in artifacts
    ):
        raise ValueError("base evidence already contains the DHAT artifact")
    artifacts.append(
        {
            "kind": "dhat",
            "path": portable_path,
            "sha256": sha256_bytes(dhat_path.read_bytes()),
            "media_type": DHAT_MEDIA_TYPE,
        }
    )
    output["artifacts"] = artifacts

    extensions = dict(output.get("extensions", {}))
    if "profiler.dhat" in extensions:
        raise ValueError("base evidence already defines profiler.dhat extension")
    unavailable_heap_fields = []
    if dhat["mode"] in {"heap", "rust-heap"}:
        for field in ("gb", "gbk", "eb", "ebk", "rb", "wb"):
            if optional_sum(dhat["pps"], field) is None:
                unavailable_heap_fields.append(field)
    extensions["profiler.dhat"] = {
        "adapter_contract": ADAPTER_CONTRACT,
        "dhat_file_version": dhat["dhatFileVersion"],
        "mode": dhat["mode"],
        "verb": dhat.get("verb"),
        "time_unit": dhat.get("tu"),
        "program_points": len(dhat["pps"]),
        "unavailable_heap_fields": unavailable_heap_fields,
    }
    output["extensions"] = extensions

    validate_evidence(output, "converted evidence")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich canonical Performance Evidence with DHAT allocation "
            "or copy-profile measurements."
        )
    )
    parser.add_argument("base_evidence", type=Path)
    parser.add_argument("dhat", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--artifact-path",
        help=(
            "Portable path stored in the canonical artifact; "
            "defaults to the DHAT input filename."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        base_evidence = load_json_object(args.base_evidence)
        converted = convert(base_evidence, args.dhat, args.artifact_path)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(converted, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"DHAT conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"Wrote DHAT Performance Evidence to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
