#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from validate_schema import SCHEMA_PATH, load_json, validation_errors

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_SCHEMA_PATH = ROOT / "schema" / "performance-comparison.schema.json"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def validate_evidence(path: Path) -> dict[str, Any]:
    schema = load_json(SCHEMA_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    document = load_json(path)
    errors = validation_errors(validator, document)
    if errors:
        raise ValueError(
            f"{path} is not valid Performance Evidence:\n  - " + "\n  - ".join(errors)
        )
    return document


def evidence_identity(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    workload = document["scenario"]["workload"]
    return {
        "evidence_hash": sha256_file(path),
        "source_revision": document["source"]["revision"],
        "dirty": document["source"]["dirty"],
        "scenario_id": document["scenario"]["id"],
        "workload_id": workload["id"],
        "workload_hash": workload["hash"],
        "environment_fingerprint": document["environment"]["fingerprint"],
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
            "value": (candidate_value - baseline_value) / baseline_value,
        }
    return result


def compare_documents(
    baseline_path: Path,
    candidate_path: Path,
    expected_candidate_revision: str | None = None,
) -> dict[str, Any]:
    baseline = validate_evidence(baseline_path)
    candidate = validate_evidence(candidate_path)

    baseline_hash = sha256_file(baseline_path)
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

    comparability: dict[str, Any] = {
        "status": "comparable" if scenario_comparable else "incomparable",
        "reasons": reasons,
    }
    if expected_candidate_revision is not None:
        comparability["expected_candidate_revision"] = expected_candidate_revision

    comparison = {
        "schema_version": "1.0.0",
        "kind": "performance-evidence/comparison",
        "candidate": evidence_identity(candidate_path, candidate),
        "baseline": evidence_identity(baseline_path, baseline),
        "comparability": comparability,
        "measurements": [
            compare_measurement(
                name,
                baseline_measurements.get(name),
                candidate_measurements.get(name),
                scenario_comparable,
            )
            for name in names
        ],
    }

    comparison_schema = load_json(COMPARISON_SCHEMA_PATH)
    Draft202012Validator.check_schema(comparison_schema)
    validator = Draft202012Validator(
        comparison_schema,
        format_checker=FormatChecker(),
    )
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        comparison = compare_documents(
            args.baseline,
            args.candidate,
            args.expected_candidate_revision,
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
