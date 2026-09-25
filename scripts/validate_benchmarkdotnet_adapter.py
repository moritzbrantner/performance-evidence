#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from convert_benchmarkdotnet import convert, load_json_object, sha256_bytes
from validate_schema import validation_errors


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "benchmarkdotnet"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
SELECTOR = "Example.TableBenchmarks.Materialize"


def expect_value_error(action, expected_fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if expected_fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {expected_fragment!r}")


def measurement_map(document: dict) -> dict[str, dict]:
    return {
        entry["name"]: entry
        for group in ("useful_work", "induced_work", "outcomes")
        for entry in document["measurements"][group]
    }


def main() -> int:
    try:
        base = load_json_object(FIXTURE_DIR / "base-evidence.json")
        benchmark_path = FIXTURE_DIR / "benchmarkdotnet.json"

        expect_value_error(
            lambda: convert(base, benchmark_path),
            "multiple benchmarks",
        )

        converted = convert(
            base,
            benchmark_path,
            SELECTOR,
            "profiling/benchmarkdotnet.json",
        )

        if converted["scenario"] != base["scenario"]:
            raise ValueError("BenchmarkDotNet adapter changed scenario/workload authority")
        if converted["source"] != base["source"]:
            raise ValueError("BenchmarkDotNet adapter changed source authority")
        if converted["measurements"]["useful_work"] != base["measurements"]["useful_work"]:
            raise ValueError("BenchmarkDotNet adapter changed domain-owned useful work")
        if converted["measurements"]["outcomes"] != base["measurements"]["outcomes"]:
            raise ValueError("BenchmarkDotNet adapter promoted timing into canonical outcomes")
        if (
            converted["measurements"]["induced_work"][
                : len(base["measurements"]["induced_work"])
            ]
            != base["measurements"]["induced_work"]
        ):
            raise ValueError("BenchmarkDotNet adapter changed existing induced work")

        mapped = measurement_map(converted)
        expected = {
            "dotnet.benchmark_operations": (1000, "operation", "counter"),
            "dotnet.gc.gen0_collections": (3, "count", "counter"),
            "dotnet.gc.gen1_collections": (1, "count", "counter"),
            "dotnet.gc.gen2_collections": (0, "count", "counter"),
            "memory.allocated_bytes_per_operation": (
                256,
                "byte/operation",
                "size",
            ),
        }
        for name, (value, unit, measurement_type) in expected.items():
            if mapped.get(name) != {
                "name": name,
                "value": value,
                "unit": unit,
                "measurement_type": measurement_type,
            }:
                raise ValueError(
                    f"unexpected BenchmarkDotNet measurement {name}: {mapped.get(name)!r}"
                )

        extension = converted["extensions"]["dotnet.benchmarkdotnet"]
        if extension != {
            "adapter_contract": "benchmarkdotnet-memory/v1",
            "title": "TableBenchmarks",
            "benchmarkdotnet_version": "0.15.8-fixture",
            "benchmark_full_name": SELECTOR,
            "benchmark_display_info": "TableBenchmarks.Materialize: DefaultJob(N=1000)",
            "total_operations": 1000,
            "allocated_bytes_per_operation_available": True,
            "gc_counts_are_raw": True,
        }:
            raise ValueError("BenchmarkDotNet adapter emitted unexpected provenance extension")

        artifact = converted["artifacts"][-1]
        if artifact != {
            "kind": "benchmarkdotnet",
            "path": "profiling/benchmarkdotnet.json",
            "sha256": sha256_bytes(benchmark_path.read_bytes()),
            "media_type": "application/json",
        }:
            raise ValueError("BenchmarkDotNet raw artifact provenance is incorrect")

        toolchain = converted["environment"]["toolchain"]
        if toolchain.get("benchmarkdotnet") != "0.15.8-fixture":
            raise ValueError("BenchmarkDotNet version was not fingerprinted")
        if toolchain.get("dotnet_runtime") != ".NET 10.0.0":
            raise ValueError(".NET runtime was not fingerprinted")
        if toolchain.get("dotnet_cli") != "10.0.100":
            raise ValueError(".NET CLI was not fingerprinted")
        if converted["environment"]["fingerprint"] == base["environment"]["fingerprint"]:
            raise ValueError("BenchmarkDotNet adapter did not derive an environment identity")

        schema = load_json_object(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = validation_errors(validator, converted)
        if errors:
            raise ValueError(
                "converted BenchmarkDotNet evidence violates canonical contract:\n  - "
                + "\n  - ".join(errors)
            )

        by_display = convert(
            base,
            benchmark_path,
            "TableBenchmarks.Materialize: DefaultJob(N=1000)",
        )
        if (
            by_display["extensions"]["dotnet.benchmarkdotnet"]["benchmark_full_name"]
            != SELECTOR
        ):
            raise ValueError("DisplayInfo selector did not resolve the intended benchmark")

        expect_value_error(
            lambda: convert(base, benchmark_path, "missing"),
            "matched nothing",
        )
        expect_value_error(
            lambda: convert(base, benchmark_path, "Example.TableBenchmarks.Scan"),
            "no observed memory diagnostics",
        )

        collision = copy.deepcopy(base)
        collision["measurements"]["induced_work"].append(
            {
                "name": "dotnet.gc.gen0_collections",
                "value": 99,
                "unit": "count",
                "measurement_type": "counter",
            }
        )
        expect_value_error(
            lambda: convert(collision, benchmark_path, SELECTOR),
            "collide",
        )

        extension_collision = copy.deepcopy(base)
        extension_collision["extensions"] = {
            "dotnet.benchmarkdotnet": {"owner": "repository"}
        }
        expect_value_error(
            lambda: convert(extension_collision, benchmark_path, SELECTOR),
            "already defines dotnet.benchmarkdotnet",
        )

        artifact_collision = copy.deepcopy(base)
        artifact_collision["artifacts"] = [
            {
                "kind": "benchmarkdotnet",
                "path": "existing.json",
                "sha256": "sha256:" + "0" * 64,
            }
        ]
        expect_value_error(
            lambda: convert(artifact_collision, benchmark_path, SELECTOR),
            "already contains the BenchmarkDotNet artifact",
        )

        expect_value_error(
            lambda: convert(base, benchmark_path, SELECTOR, "/tmp/benchmark.json"),
            "portable relative POSIX path",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)

            destructive_path = temporary / "raw.json"
            destructive_bytes = benchmark_path.read_bytes()
            destructive_path.write_bytes(destructive_bytes)
            destructive = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "convert_benchmarkdotnet.py"),
                    str(FIXTURE_DIR / "base-evidence.json"),
                    str(destructive_path),
                    "--benchmark",
                    SELECTOR,
                    "--output",
                    str(destructive_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if destructive.returncode != 1:
                raise ValueError("destructive output/input collision unexpectedly succeeded")
            if destructive_path.read_bytes() != destructive_bytes:
                raise ValueError("rejected destructive conversion modified the raw input")

            single_path = temporary / "single.json"
            source = load_json_object(benchmark_path)
            source["Benchmarks"] = [source["Benchmarks"][0]]
            single_path.write_text(
                json.dumps(source, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            single = convert(base, single_path)
            if (
                single["extensions"]["dotnet.benchmarkdotnet"]["benchmark_full_name"]
                != SELECTOR
            ):
                raise ValueError("single benchmark input did not auto-select")

            gc_only_path = temporary / "gc-only.json"
            gc_only = copy.deepcopy(source)
            gc_only["Benchmarks"][0]["Memory"]["BytesAllocatedPerOperation"] = None
            gc_only_path.write_text(
                json.dumps(gc_only, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            gc_only_result = convert(base, gc_only_path)
            gc_only_names = measurement_map(gc_only_result)
            if "memory.allocated_bytes_per_operation" in gc_only_names:
                raise ValueError("missing allocation telemetry was coerced into a value")
            if gc_only_names["dotnet.gc.gen0_collections"]["value"] != 3:
                raise ValueError("GC evidence was lost when allocation telemetry was absent")

            malformed_path = temporary / "malformed.json"
            malformed = copy.deepcopy(source)
            malformed["Benchmarks"][0]["Memory"]["Gen0Collections"] = -1
            malformed_path.write_text(
                json.dumps(malformed, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            expect_value_error(
                lambda: convert(base, malformed_path),
                "Gen0Collections",
            )

            runtime_path = temporary / "runtime.json"
            runtime = copy.deepcopy(source)
            runtime["HostEnvironmentInfo"]["RuntimeVersion"] = ".NET 10.0.1"
            runtime_path.write_text(
                json.dumps(runtime, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            runtime_result = convert(base, runtime_path)
            if (
                runtime_result["environment"]["fingerprint"]
                == single["environment"]["fingerprint"]
            ):
                raise ValueError("runtime drift did not change environment fingerprint")

    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BenchmarkDotNet adapter validation failed: {error}", file=sys.stderr)
        return 1

    print("BenchmarkDotNet memory adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
