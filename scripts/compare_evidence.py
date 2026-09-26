#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from input_snapshot import InputSnapshot, read_input_snapshot
from output_paths import validate_output_path
from validate_schema import (
    SCHEMA_PATH,
    load_json_bytes,
    validation_errors,
    validator_for_schema,
)

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_SCHEMA_PATH = ROOT / "schema" / "performance-comparison.schema.json"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")


def validate_evidence(
    path: Path,
    snapshot: InputSnapshot,
) -> dict[str, Any]:
    document = load_json_bytes(snapshot.contents)
    errors = validation_errors(validator_for_schema(SCHEMA_PATH), document)
    if errors:
        raise ValueError(
            f"{path} is not valid Performance Evidence:\n  - " + "\n  - ".join(errors)
        )
    return document


def evidence_identity(
    snapshot: InputSnapshot,
    document: dict[str, Any],
) -> dict[str, Any]:
    workload = document["scenario"]["workload"]
    return {
        "evidence_hash": snapshot.sha256,
        "source_repository": document["source"].get("repository"),
        "source_revision": document["source"]["revision"],
        "dirty": document["source"]["dirty"],
        "scenario_id": document["scenario"]["id"],
        "workload_id": workload["id"],
        "workload_hash": workload["hash"],
        "workload_seed": workload.get("seed"),
        "workload_parameters": workload.get("parameters"),
        "environment_fingerprint": document["environment"]["fingerprint"],
        "declared_baseline": document.get("baseline"),
    }


def workload_identity(document: dict[str, Any]) -> tuple[Any, ...]:
    workload = document["scenario"]["workload"]
    return (
        workload["id"],
        workload["hash"],
        workload.get("seed"),
        workload.get("parameters"),
    )


def comparability_reasons(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_hash: str,
    expected_candidate_revision: str | None,
) -> list[str]:
    reasons: list[str] = []

    if candidate["source"]["dirty"]:
        reasons.append("candidate_dirty")
    if baseline["source"]["dirty"]:
        reasons.append("baseline_dirty")
    if (
        expected_candidate_revision is not None
        and candidate["source"]["revision"] != expected_candidate_revision
    ):
        reasons.append("candidate_revision_mismatch")
    if candidate["source"].get("repository") != baseline["source"].get("repository"):
        reasons.append("repository_mismatch")
    if candidate["scenario"]["id"] != baseline["scenario"]["id"]:
        reasons.append("scenario_mismatch")
    if workload_identity(candidate) != workload_identity(baseline):
        reasons.append("workload_mismatch")
    if candidate["environment"]["fingerprint"] != baseline["environment"]["fingerprint"]:
        reasons.append("environment_mismatch")

    declared_baseline = candidate.get("baseline")
    if declared_baseline is not None and (
        declared_baseline["source_revision"] != baseline["source"]["revision"]
        or declared_baseline["evidence_hash"] != baseline_hash
    ):
        reasons.append("declared_baseline_mismatch")

    return reasons


def measurement_index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for group in MEASUREMENT_GROUPS:
        for measurement in document["measurements"][group]:
            result[measurement["name"]] = {
                "group": group,
                "unit": measurement["unit"],
                "measurement_type": measurement["measurement_type"],
                "value": measurement["value"],
            }
    return result


def unavailable_relative_delta() -> dict[str, Any]:
    return {"status": "unavailable", "value": None}


def finite_divide(
    numerator: int | float,
    denominator: int | float,
    label: str,
) -> float:
    try:
        value = numerator / denominator
    except OverflowError as error:
        raise ValueError(f"{label} overflowed") from error
    if not math.isfinite(value):
        raise ValueError(f"{label} produced a non-finite value")
    return value


def parse_amplification_spec(value: str) -> tuple[str, str, str]:
    try:
        name, operands = value.split("=", 1)
        numerator, denominator = operands.split(",", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "amplification must use NAME=NUMERATOR,DENOMINATOR"
        ) from error

    if not name or not numerator or not denominator:
        raise argparse.ArgumentTypeError(
            "amplification name, numerator, and denominator must be non-empty"
        )
    return name, numerator, denominator


def ratio_snapshot(
    measurements: dict[str, dict[str, Any]],
    numerator: str,
    denominator: str,
    *,
    blocked_status: str | None = None,
) -> dict[str, Any]:
    numerator_measurement = measurements.get(numerator)
    denominator_measurement = measurements.get(denominator)
    numerator_value = (
        None if numerator_measurement is None else numerator_measurement["value"]
    )
    denominator_value = (
        None if denominator_measurement is None else denominator_measurement["value"]
    )

    if blocked_status is not None:
        return {
            "status": blocked_status,
            "numerator_value": numerator_value,
            "denominator_value": denominator_value,
            "value": None,
        }
    if numerator_measurement is None:
        return {
            "status": "missing_numerator",
            "numerator_value": None,
            "denominator_value": denominator_value,
            "value": None,
        }
    if denominator_measurement is None:
        return {
            "status": "missing_denominator",
            "numerator_value": numerator_value,
            "denominator_value": None,
            "value": None,
        }
    if denominator_value == 0:
        return {
            "status": "undefined_zero_denominator",
            "numerator_value": numerator_value,
            "denominator_value": denominator_value,
            "value": None,
        }
    return {
        "status": "defined",
        "numerator_value": numerator_value,
        "denominator_value": denominator_value,
        "value": finite_divide(
            numerator_value,
            denominator_value,
            f"amplification {numerator}/{denominator}",
        ),
    }


def compare_amplification(
    name: str,
    numerator: str,
    denominator: str,
    baseline_measurements: dict[str, dict[str, Any]],
    candidate_measurements: dict[str, dict[str, Any]],
    measurement_comparisons: dict[str, dict[str, Any]],
    scenario_comparable: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "numerator": numerator,
        "denominator": denominator,
        "status": "scenario_incomparable",
        "baseline": ratio_snapshot(
            baseline_measurements,
            numerator,
            denominator,
            blocked_status="scenario_incomparable",
        ),
        "candidate": ratio_snapshot(
            candidate_measurements,
            numerator,
            denominator,
            blocked_status="scenario_incomparable",
        ),
        "absolute_delta": None,
        "relative_delta": unavailable_relative_delta(),
    }

    if not scenario_comparable:
        return result

    input_comparisons = [
        measurement_comparisons.get(numerator),
        measurement_comparisons.get(denominator),
    ]
    if any(entry is None for entry in input_comparisons) or any(
        entry["status"] in {"missing_baseline", "missing_candidate"}
        for entry in input_comparisons
        if entry is not None
    ):
        result["status"] = "missing_measurement"
        result["baseline"] = ratio_snapshot(
            baseline_measurements, numerator, denominator
        )
        result["candidate"] = ratio_snapshot(
            candidate_measurements, numerator, denominator
        )
        return result

    if any(
        entry["status"] == "incompatible_definition"
        for entry in input_comparisons
        if entry is not None
    ):
        result["status"] = "incompatible_definition"
        result["baseline"] = ratio_snapshot(
            baseline_measurements,
            numerator,
            denominator,
            blocked_status="incompatible_definition",
        )
        result["candidate"] = ratio_snapshot(
            candidate_measurements,
            numerator,
            denominator,
            blocked_status="incompatible_definition",
        )
        return result

    result["baseline"] = ratio_snapshot(
        baseline_measurements, numerator, denominator
    )
    result["candidate"] = ratio_snapshot(
        candidate_measurements, numerator, denominator
    )
    if (
        result["baseline"]["status"] == "undefined_zero_denominator"
        or result["candidate"]["status"] == "undefined_zero_denominator"
    ):
        result["status"] = "undefined_zero_denominator"
        return result

    if (
        result["baseline"]["status"] != "defined"
        or result["candidate"]["status"] != "defined"
    ):
        result["status"] = "missing_measurement"
        return result

    baseline_value = result["baseline"]["value"]
    candidate_value = result["candidate"]["value"]
    result["status"] = "comparable"
    result["absolute_delta"] = candidate_value - baseline_value
    if baseline_value == 0:
        result["relative_delta"] = {
            "status": "undefined_zero_baseline",
            "value": None,
        }
    else:
        result["relative_delta"] = {
            "status": "defined",
            "value": finite_divide(
                candidate_value - baseline_value,
                baseline_value,
                f"relative amplification delta {name}",
            ),
        }
    return result


def compare_measurement(
    name: str,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    scenario_comparable: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "status": "scenario_incomparable",
        "baseline": baseline,
        "candidate": candidate,
        "absolute_delta": None,
        "relative_delta": unavailable_relative_delta(),
    }

    if not scenario_comparable:
        return result
    if baseline is None:
        result["status"] = "missing_baseline"
        return result
    if candidate is None:
        result["status"] = "missing_candidate"
        return result

    definition_fields = ("group", "unit", "measurement_type")
    if any(baseline[field] != candidate[field] for field in definition_fields):
        result["status"] = "incompatible_definition"
        return result

    baseline_value = baseline["value"]
    candidate_value = candidate["value"]
    result["status"] = "comparable"
    result["absolute_delta"] = candidate_value - baseline_value
    if baseline_value == 0:
        result["relative_delta"] = {
            "status": "undefined_zero_baseline",
            "value": None,
        }
    else:
        result["relative_delta"] = {
            "status": "defined",
            "value": finite_divide(
                candidate_value - baseline_value,
                baseline_value,
                f"relative measurement delta {name}",
            ),
        }
    return result


def compare_documents(
    baseline_path: Path,
    candidate_path: Path,
    expected_candidate_revision: str | None = None,
    amplification_specs: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    baseline_snapshot = read_input_snapshot(baseline_path)
    candidate_snapshot = read_input_snapshot(candidate_path)
    baseline = validate_evidence(baseline_path, baseline_snapshot)
    candidate = validate_evidence(candidate_path, candidate_snapshot)

    baseline_hash = baseline_snapshot.sha256
    reasons = comparability_reasons(
        baseline,
        candidate,
        baseline_hash,
        expected_candidate_revision,
    )
    scenario_comparable = not reasons

    baseline_measurements = measurement_index(baseline)
    candidate_measurements = measurement_index(candidate)
    names = sorted(set(baseline_measurements) | set(candidate_measurements))
    measurement_entries = [
        compare_measurement(
            name,
            baseline_measurements.get(name),
            candidate_measurements.get(name),
            scenario_comparable,
        )
        for name in names
    ]
    measurement_comparisons = {
        entry["name"]: entry for entry in measurement_entries
    }

    specs = amplification_specs or []
    amplification_names = [name for name, _, _ in specs]
    if len(amplification_names) != len(set(amplification_names)):
        raise ValueError("amplification names must be unique")

    comparability: dict[str, Any] = {
        "status": "comparable" if scenario_comparable else "incomparable",
        "reasons": reasons,
    }
    if expected_candidate_revision is not None:
        comparability["expected_candidate_revision"] = expected_candidate_revision

    comparison = {
        "schema_version": "1.0.0",
        "kind": "performance-evidence/comparison",
        "candidate": evidence_identity(candidate_snapshot, candidate),
        "baseline": evidence_identity(baseline_snapshot, baseline),
        "comparability": comparability,
        "measurements": measurement_entries,
    }
    if specs:
        comparison["amplifications"] = [
            compare_amplification(
                name,
                numerator,
                denominator,
                baseline_measurements,
                candidate_measurements,
                measurement_comparisons,
                scenario_comparable,
            )
            for name, numerator, denominator in specs
        ]

    validator = validator_for_schema(COMPARISON_SCHEMA_PATH)
    errors = sorted(
        validator.iter_errors(comparison),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        detail = "\n  - ".join(
            f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
            for error in errors
        )
        raise RuntimeError(f"generated comparison failed its contract:\n  - {detail}")

    return comparison


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare exact Performance Evidence artifacts without coercing missing or incomparable measurements."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-candidate-revision",
        help="Optional reviewed head SHA/revision that the candidate evidence must match.",
    )
    parser.add_argument(
        "--amplification",
        action="append",
        default=[],
        type=parse_amplification_spec,
        metavar="NAME=NUMERATOR,DENOMINATOR",
        help=(
            "Explicit domain-owned amplification ratio to derive. "
            "May be supplied more than once."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_output_path(args.output, (args.baseline, args.candidate))
        comparison = compare_documents(
            args.baseline,
            args.candidate,
            args.expected_candidate_revision,
            args.amplification,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Performance Evidence comparison failed: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(comparison, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Performance Evidence comparison written to {args.output} "
        f"({comparison['comparability']['status']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
