#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from output_paths import write_text_atomic
from validate_schema import validation_errors


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
SCENARIO_ID = "agent/implementation-attempt"
EXTENSION_NAMESPACE = "agent.execution"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")
PROFILE_MEASUREMENTS = {
    "agent.candidate_produced": ("count", "counter"),
    "agent.input_tokens": ("token", "counter"),
    "agent.output_tokens": ("token", "counter"),
    "agent.cached_input_tokens": ("token", "counter"),
    "agent.execution_time": ("ms", "duration"),
    "agent.deterministic_time_to_green": ("ms", "duration"),
    "agent.cost": ("usd", "gauge"),
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def input_digest(documents: Iterable[dict[str, Any]]) -> str:
    hashes = sorted(sha256_bytes(canonical_json(document)) for document in documents)
    return sha256_bytes(("\n".join(hashes) + "\n").encode("utf-8"))


def attempt_identity(document: dict[str, Any]) -> tuple[str, str]:
    extension_root = document.get("extensions")
    extension = (
        extension_root.get(EXTENSION_NAMESPACE)
        if isinstance(extension_root, dict)
        else None
    )
    if isinstance(extension, dict):
        attempt_id = extension.get("attempt_id")
        if isinstance(attempt_id, str) and attempt_id:
            return ("attempt_id", attempt_id)

        run_id = extension.get("run_id")
        attempt_number = extension.get("attempt_number")
        if (
            isinstance(run_id, str)
            and run_id
            and isinstance(attempt_number, int)
            and not isinstance(attempt_number, bool)
            and attempt_number >= 1
        ):
            return ("run_attempt", f"{run_id}:{attempt_number}")

    return ("document_hash", sha256_bytes(canonical_json(document)))


def deduplicate_documents(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], bytes] = {}
    for document in documents:
        identity = attempt_identity(document)
        encoded = canonical_json(document)
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = encoded
            unique.append(document)
            continue
        if previous != encoded:
            raise ValueError(
                "conflicting evidence for the same agent attempt identity "
                f"{identity[0]}={identity[1]!r}"
            )
    return unique


def measurement_index(document: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], int]:
    result: dict[str, dict[str, Any]] = {}
    examined = 0
    measurements = document.get("measurements")
    if not isinstance(measurements, dict):
        raise ValueError("canonical evidence is missing measurements")
    for group in MEASUREMENT_GROUPS:
        entries = measurements.get(group)
        if not isinstance(entries, list):
            raise ValueError(f"canonical evidence is missing measurements.{group}")
        for entry in entries:
            examined += 1
            if not isinstance(entry, dict):
                raise ValueError(f"measurements.{group} entries must be objects")
            name = entry.get("name")
            if isinstance(name, str):
                result[name] = entry
    return result, examined


def measurement_value(index: dict[str, dict[str, Any]], name: str) -> int | float | None:
    entry = index.get(name)
    if entry is None:
        return None
    expected_unit, expected_type = PROFILE_MEASUREMENTS[name]
    if entry.get("unit") != expected_unit or entry.get("measurement_type") != expected_type:
        raise ValueError(
            f"{name} must use unit={expected_unit!r} and measurement_type={expected_type!r}"
        )
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must contain a non-negative numeric value")
    return value


def mean(values: list[int | float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stable_median(values: list[int | float]) -> float | int | None:
    if not values:
        return None
    return median(values)


def increment(counter: Counter[str], value: Any, *, missing: str = "<missing>") -> None:
    if isinstance(value, str) and value:
        counter[value] += 1
    else:
        counter[missing] += 1


def summarize_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    loaded_document_count = len(documents)
    documents = deduplicate_documents(documents)

    provider_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    repository_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    escalation_reason_counts: Counter[str] = Counter()

    input_tokens: list[int | float] = []
    output_tokens: list[int | float] = []
    cached_input_tokens: list[int | float] = []
    costs: list[int | float] = []
    execution_times: list[int | float] = []
    time_to_green: list[int | float] = []
    candidate_count = 0
    measurements_examined = 0

    for document in documents:
        scenario = document.get("scenario")
        if not isinstance(scenario, dict) or scenario.get("id") != SCENARIO_ID:
            raise ValueError(f"all rollup inputs must use scenario.id={SCENARIO_ID!r}")

        extension_root = document.get("extensions")
        extension = (
            extension_root.get(EXTENSION_NAMESPACE)
            if isinstance(extension_root, dict)
            else None
        )
        if not isinstance(extension, dict):
            raise ValueError(f"all rollup inputs must include extensions.{EXTENSION_NAMESPACE}")

        index, examined = measurement_index(document)
        measurements_examined += examined

        candidate = measurement_value(index, "agent.candidate_produced")
        if candidate not in {0, 1}:
            raise ValueError("agent.candidate_produced must be 0 or 1")
        candidate_count += int(candidate)

        for name, target in (
            ("agent.input_tokens", input_tokens),
            ("agent.output_tokens", output_tokens),
            ("agent.cached_input_tokens", cached_input_tokens),
            ("agent.cost", costs),
            ("agent.execution_time", execution_times),
            ("agent.deterministic_time_to_green", time_to_green),
        ):
            value = measurement_value(index, name)
            if value is not None:
                target.append(value)

        increment(provider_counts, extension.get("provider"))
        increment(model_counts, extension.get("model"))
        increment(outcome_counts, extension.get("outcome"))
        if extension.get("escalation_reason") is not None:
            increment(escalation_reason_counts, extension.get("escalation_reason"))

        source = document.get("source")
        repository = source.get("repository") if isinstance(source, dict) else None
        increment(repository_counts, repository)

    attempt_count = len(documents)
    observed_totals: dict[str, int | float] = {}
    for name, values in (
        ("input_tokens", input_tokens),
        ("output_tokens", output_tokens),
        ("cached_input_tokens", cached_input_tokens),
        ("cost_usd", costs),
    ):
        if values:
            observed_totals[name] = sum(values)

    duration_summary: dict[str, int | float] = {}
    for prefix, values in (
        ("execution_time_ms", execution_times),
        ("deterministic_time_to_green_ms", time_to_green),
    ):
        average = mean(values)
        middle = stable_median(values)
        if average is not None:
            duration_summary[f"mean_{prefix}"] = average
        if middle is not None:
            duration_summary[f"median_{prefix}"] = middle

    return {
        "schema_version": 1,
        "kind": "agent-efficiency-rollup",
        "profile": "agent-run/v1",
        "input_digest": input_digest(documents),
        "summary": {
            "attempt_count": attempt_count,
            "candidate_count": candidate_count,
            "provider_counts": dict(sorted(provider_counts.items())),
            "model_counts": dict(sorted(model_counts.items())),
            "repository_counts": dict(sorted(repository_counts.items())),
            "outcome_counts": dict(sorted(outcome_counts.items())),
            "escalation_reason_counts": dict(sorted(escalation_reason_counts.items())),
            "observed_totals": observed_totals,
            "durations": duration_summary,
            "telemetry_coverage": {
                "input_tokens": len(input_tokens),
                "output_tokens": len(output_tokens),
                "cached_input_tokens": len(cached_input_tokens),
                "cost_usd": len(costs),
                "execution_time_ms": len(execution_times),
                "deterministic_time_to_green_ms": len(time_to_green),
            },
        },
        "work": {
            "documents_loaded": loaded_document_count,
            "duplicate_documents_ignored": loaded_document_count - attempt_count,
            "measurement_entries_examined": measurements_examined,
        },
    }


def find_evidence(input_dir: Path, exclude: Path | None = None) -> list[Path]:
    excluded = exclude.resolve() if exclude is not None else None
    return sorted(
        path
        for path in input_dir.rglob("*.json")
        if path.is_file() and (excluded is None or path.resolve() != excluded)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize canonical agent-run Performance Evidence into a deterministic weekly-style rollup."
    )
    parser.add_argument("input_dir", type=Path, help="directory containing canonical per-attempt evidence")
    parser.add_argument("--output", type=Path, help="optional path for the machine-readable rollup")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        schema = load_json(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        paths = find_evidence(args.input_dir, args.output)
        if not paths:
            raise ValueError(f"no JSON evidence found below {args.input_dir}")
        documents = []
        for path in paths:
            document = load_json(path)
            errors = validation_errors(validator, document)
            if errors:
                raise ValueError(
                    f"{path} violates canonical Performance Evidence:\n  - "
                    + "\n  - ".join(errors)
                )
            documents.append(document)
        rollup = summarize_documents(documents)
        rendered = json.dumps(rollup, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            write_text_atomic(args.output, rendered)
        sys.stdout.write(rendered)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Agent evidence rollup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
