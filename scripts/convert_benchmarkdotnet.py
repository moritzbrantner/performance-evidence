#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from output_paths import validate_output_path
from validate_schema import (
    SCHEMA_PATH,
    load_json,
    validation_errors,
    validator_for_schema,
)


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_NAME = "performance-evidence.benchmarkdotnet-adapter"
COLLECTOR_VERSION = "1.0.0"
ADAPTER_CONTRACT = "benchmarkdotnet-memory/v1"
ARTIFACT_MEDIA_TYPE = "application/json"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_evidence(document: dict[str, Any], label: str) -> None:
    errors = validation_errors(validator_for_schema(SCHEMA_PATH), document)
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


def optional_nonempty_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string when present")
    return value


def benchmark_entries(document: dict[str, Any]) -> list[dict[str, Any]]:
    entries = document.get("Benchmarks")
    if not isinstance(entries, list) or not entries:
        raise ValueError("BenchmarkDotNet JSON must contain a non-empty Benchmarks array")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"BenchmarkDotNet Benchmarks[{index}] must be an object")
    return entries


def select_benchmark(
    document: dict[str, Any],
    selector: str | None,
) -> dict[str, Any]:
    entries = benchmark_entries(document)
    if selector is None:
        if len(entries) != 1:
            raise ValueError(
                "BenchmarkDotNet JSON contains multiple benchmarks; "
                "select one with --benchmark"
            )
        return entries[0]

    matches = [
        entry
        for entry in entries
        if entry.get("FullName") == selector or entry.get("DisplayInfo") == selector
    ]
    if not matches:
        raise ValueError(f"BenchmarkDotNet benchmark selector {selector!r} matched nothing")
    if len(matches) != 1:
        raise ValueError(
            f"BenchmarkDotNet benchmark selector {selector!r} is ambiguous"
        )
    return matches[0]


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


def memory_measurements(benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    memory = benchmark.get("Memory")
    if not isinstance(memory, dict):
        raise ValueError("selected BenchmarkDotNet benchmark has no Memory diagnostics")

    total_operations = nonnegative_integer(
        memory.get("TotalOperations"),
        "BenchmarkDotNet Memory.TotalOperations",
    )
    allocated = memory.get("BytesAllocatedPerOperation")
    if allocated is not None:
        allocated = nonnegative_integer(
            allocated,
            "BenchmarkDotNet Memory.BytesAllocatedPerOperation",
        )

    collections = {
        generation: nonnegative_integer(
            memory.get(field),
            f"BenchmarkDotNet Memory.{field}",
        )
        for generation, field in (
            ("gen0", "Gen0Collections"),
            ("gen1", "Gen1Collections"),
            ("gen2", "Gen2Collections"),
        )
    }

    if total_operations == 0:
        if allocated is not None or any(collections.values()):
            raise ValueError(
                "BenchmarkDotNet memory diagnostics are inconsistent: "
                "zero TotalOperations with observed allocation/GC values"
            )
        raise ValueError(
            "selected BenchmarkDotNet benchmark has no observed memory diagnostics"
        )

    result = [
        measurement(
            "dotnet.benchmark_operations",
            total_operations,
            "operation",
            "counter",
        ),
        *[
            measurement(
                f"dotnet.gc.{generation}_collections",
                value,
                "count",
                "counter",
            )
            for generation, value in collections.items()
        ],
    ]
    if allocated is not None:
        result.append(
            measurement(
                "memory.allocated_bytes_per_operation",
                allocated,
                "byte/operation",
                "size",
            )
        )
    return result


def measurement_names(document: dict[str, Any]) -> set[str]:
    return {
        entry["name"]
        for group in ("useful_work", "induced_work", "outcomes")
        for entry in document["measurements"][group]
    }


def adapter_environment(
    environment: dict[str, Any],
    document: dict[str, Any],
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    host = document.get("HostEnvironmentInfo")
    if not isinstance(host, dict):
        raise ValueError("BenchmarkDotNet JSON is missing HostEnvironmentInfo")

    benchmarkdotnet_version = optional_nonempty_string(
        host.get("BenchmarkDotNetVersion"),
        "BenchmarkDotNetVersion",
    )
    runtime_version = optional_nonempty_string(
        host.get("RuntimeVersion"),
        "RuntimeVersion",
    )
    architecture = optional_nonempty_string(
        host.get("Architecture"),
        "Architecture",
    )
    configuration = optional_nonempty_string(
        host.get("Configuration"),
        "Configuration",
    )
    dotnet_cli = optional_nonempty_string(
        host.get("DotNetCliVersion"),
        "DotNetCliVersion",
    )
    display_info = optional_nonempty_string(
        benchmark.get("DisplayInfo"),
        "selected benchmark DisplayInfo",
    )
    full_name = optional_nonempty_string(
        benchmark.get("FullName"),
        "selected benchmark FullName",
    )

    if benchmarkdotnet_version is None or runtime_version is None or architecture is None:
        raise ValueError(
            "BenchmarkDotNet host identity requires BenchmarkDotNetVersion, "
            "RuntimeVersion, and Architecture"
        )
    if display_info is None or full_name is None:
        raise ValueError(
            "selected BenchmarkDotNet benchmark requires DisplayInfo and FullName"
        )

    result = copy.deepcopy(environment)
    original_collector = result.get("collector")
    toolchain = dict(result.get("toolchain", {}))
    toolchain["benchmarkdotnet"] = benchmarkdotnet_version
    toolchain["dotnet_runtime"] = runtime_version
    if dotnet_cli is not None:
        toolchain["dotnet_cli"] = dotnet_cli
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
            "benchmarkdotnet_version": benchmarkdotnet_version,
            "runtime_version": runtime_version,
            "architecture": architecture,
            "configuration": configuration,
            "dotnet_cli": dotnet_cli,
            "benchmark": {
                "full_name": full_name,
                "display_info": display_info,
                "hardware_intrinsics": benchmark.get("HardwareIntrinsics"),
            },
        }
    )
    return result


def convert(
    base_evidence: dict[str, Any],
    benchmarkdotnet_path: Path,
    benchmark_selector: str | None = None,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    validate_evidence(base_evidence, "base evidence")
    document = load_json_object(benchmarkdotnet_path)
    benchmark = select_benchmark(document, benchmark_selector)
    additions = memory_measurements(benchmark)

    existing_names = measurement_names(base_evidence)
    collisions = sorted(
        entry["name"] for entry in additions if entry["name"] in existing_names
    )
    if collisions:
        raise ValueError(
            "BenchmarkDotNet measurements collide with base evidence: "
            + ", ".join(collisions)
        )

    output = copy.deepcopy(base_evidence)
    output["measurements"]["induced_work"].extend(additions)
    output["environment"] = adapter_environment(
        base_evidence["environment"],
        document,
        benchmark,
    )

    portable_path = artifact_path or benchmarkdotnet_path.name
    if not portable_path:
        raise ValueError("BenchmarkDotNet artifact path must not be empty")
    artifacts = list(output.get("artifacts", []))
    if any(
        artifact.get("kind") == "benchmarkdotnet"
        or artifact.get("path") == portable_path
        for artifact in artifacts
    ):
        raise ValueError("base evidence already contains the BenchmarkDotNet artifact")
    artifacts.append(
        {
            "kind": "benchmarkdotnet",
            "path": portable_path,
            "sha256": sha256_bytes(benchmarkdotnet_path.read_bytes()),
            "media_type": ARTIFACT_MEDIA_TYPE,
        }
    )
    output["artifacts"] = artifacts

    extensions = dict(output.get("extensions", {}))
    if "dotnet.benchmarkdotnet" in extensions:
        raise ValueError(
            "base evidence already defines dotnet.benchmarkdotnet extension"
        )
    host = document["HostEnvironmentInfo"]
    extensions["dotnet.benchmarkdotnet"] = {
        "adapter_contract": ADAPTER_CONTRACT,
        "title": document.get("Title"),
        "benchmarkdotnet_version": host.get("BenchmarkDotNetVersion"),
        "benchmark_full_name": benchmark.get("FullName"),
        "benchmark_display_info": benchmark.get("DisplayInfo"),
        "total_operations": benchmark["Memory"]["TotalOperations"],
        "allocated_bytes_per_operation_available": (
            benchmark["Memory"].get("BytesAllocatedPerOperation") is not None
        ),
        "gc_counts_are_raw": True,
    }
    output["extensions"] = extensions

    validate_evidence(output, "converted evidence")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich canonical Performance Evidence with BenchmarkDotNet "
            "MemoryDiagnoser allocation/GC evidence."
        )
    )
    parser.add_argument("base_evidence", type=Path)
    parser.add_argument("benchmarkdotnet_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--benchmark",
        help="Exact BenchmarkDotNet FullName or DisplayInfo when the JSON contains multiple benchmarks.",
    )
    parser.add_argument(
        "--artifact-path",
        help=(
            "Portable path stored in the canonical artifact; "
            "defaults to the BenchmarkDotNet input filename."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_output_path(
            args.output,
            (args.base_evidence, args.benchmarkdotnet_json),
        )
        base_evidence = load_json_object(args.base_evidence)
        converted = convert(
            base_evidence,
            args.benchmarkdotnet_json,
            args.benchmark,
            args.artifact_path,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(converted, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BenchmarkDotNet conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"Wrote BenchmarkDotNet Performance Evidence to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
