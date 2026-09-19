#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from validate_schema import load_json

ROOT = Path(__file__).resolve().parents[1]
COMPARISON_SCHEMA_PATH = ROOT / "schema" / "performance-comparison.schema.json"
POLICY_SCHEMA_PATH = ROOT / "schema" / "performance-budget-policy.schema.json"
EVALUATION_SCHEMA_PATH = ROOT / "schema" / "performance-budget-evaluation.schema.json"
HARD_ELIGIBLE_MEASUREMENT_TYPES = {"counter", "gauge", "size", "ratio"}


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts
    )


def validate_document(path: Path, schema_path: Path, label: str) -> dict[str, Any]:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    document = load_json(path)
    errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        detail = "\n  - ".join(
            f"{format_path(list(error.absolute_path))}: {error.message}"
            for error in errors
        )
        raise ValueError(f"{label} is malformed:\n  - {detail}")
    return document


def validate_policy_semantics(policy: dict[str, Any]) -> None:
    ids = [rule["id"] for rule in policy["rules"]]
    if len(ids) != len(set(ids)):
        raise ValueError("budget policy rule ids must be unique")


def index_by_name(entries: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = entry["name"]
        if name in result:
            raise ValueError(f"comparison contains duplicate {label} name {name!r}")
        result[name] = entry
    return result


def exact_head_verified(comparison: dict[str, Any]) -> bool:
    expected = comparison["comparability"].get("expected_candidate_revision")
    return (
        comparison["comparability"]["status"] == "comparable"
        and expected is not None
        and expected == comparison["candidate"]["source_revision"]
    )


def hard_measurement_eligible(entry: dict[str, Any]) -> bool:
    if entry["status"] != "comparable":
        return False
    candidate = entry["candidate"]
    baseline = entry["baseline"]
    if candidate is None or baseline is None:
        return False
    if candidate["group"] == "outcomes" or baseline["group"] == "outcomes":
        return False
    return (
        candidate["measurement_type"] in HARD_ELIGIBLE_MEASUREMENT_TYPES
        and baseline["measurement_type"] in HARD_ELIGIBLE_MEASUREMENT_TYPES
    )


def hard_amplification_eligible(
    entry: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
) -> bool:
    if entry["status"] != "comparable":
        return False

    for name in (entry["numerator"], entry["denominator"]):
        source = measurements.get(name)
        if source is None or not hard_measurement_eligible(source):
            return False
    return True


def observed_values(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    candidate = entry.get("candidate")
    if kind == "measurement":
        candidate_value = None if candidate is None else candidate["value"]
    else:
        candidate_value = None if candidate is None else candidate["value"]

    relative = entry.get("relative_delta") or {
        "status": "unavailable",
        "value": None,
    }
    return {
        "candidate": candidate_value,
        "absolute_delta": entry.get("absolute_delta"),
        "relative_delta": relative.get("value"),
        "relative_delta_status": relative.get("status", "unavailable"),
    }


def assertion_value(
    assertion: dict[str, Any],
    observed: dict[str, Any],
) -> tuple[float | None, str | None]:
    kind = assertion["kind"]
    if kind == "candidate_max":
        value = observed["candidate"]
        return value, None if value is not None else "candidate value unavailable"
    if kind == "absolute_regression_max":
        value = observed["absolute_delta"]
        return value, None if value is not None else "absolute delta unavailable"
    if kind == "relative_regression_max":
        if observed["relative_delta_status"] != "defined":
            return None, (
                "relative delta unavailable: "
                + observed["relative_delta_status"]
            )
        return observed["relative_delta"], None
    raise ValueError(f"unsupported assertion kind {kind!r}")


def evaluate_rule(
    rule: dict[str, Any],
    measurements: dict[str, dict[str, Any]],
    amplifications: dict[str, dict[str, Any]],
    comparison_comparable: bool,
    exact_head: bool,
) -> dict[str, Any]:
    target = rule["target"]
    entries = measurements if target["kind"] == "measurement" else amplifications
    entry = entries.get(target["name"])

    empty_observed = {
        "candidate": None,
        "absolute_delta": None,
        "relative_delta": None,
        "relative_delta_status": "unavailable",
    }
    result = {
        "id": rule["id"],
        "target": target,
        "mode": rule["mode"],
        "assertion": rule["assertion"],
        "status": "unavailable",
        "reason": None,
        "observed": empty_observed,
    }

    if not comparison_comparable:
        result["reason"] = "comparison is not comparable"
        return result
    if not exact_head:
        result["reason"] = "comparison is not bound to the exact candidate head"
        return result
    if entry is None:
        result["reason"] = "target is missing from the comparison"
        return result

    observed = observed_values(entry, target["kind"])
    result["observed"] = observed
    if entry["status"] != "comparable":
        result["reason"] = f"target comparison status is {entry['status']}"
        return result

    if rule["mode"] == "hard":
        eligible = (
            hard_measurement_eligible(entry)
            if target["kind"] == "measurement"
            else hard_amplification_eligible(entry, measurements)
        )
        if not eligible:
            result["status"] = "ineligible_for_hard_gate"
            result["reason"] = (
                "hard gates require comparable deterministic work evidence; "
                "outcome/timing or otherwise non-deterministic targets are advisory only"
            )
            return result

    value, unavailable_reason = assertion_value(rule["assertion"], observed)
    if unavailable_reason is not None:
        result["reason"] = unavailable_reason
        return result

    result["status"] = (
        "pass" if value <= rule["assertion"]["maximum"] else "exceeded"
    )
    return result


def evaluate_budget(
    policy_path: Path,
    comparison_path: Path,
) -> dict[str, Any]:
    policy = validate_document(
        policy_path,
        POLICY_SCHEMA_PATH,
        "Performance Evidence budget policy",
    )
    validate_policy_semantics(policy)
    comparison = validate_document(
        comparison_path,
        COMPARISON_SCHEMA_PATH,
        "Performance Evidence comparison",
    )

    measurements = index_by_name(comparison["measurements"], "measurement")
    amplifications = index_by_name(
        comparison.get("amplifications", []),
        "amplification",
    )

    comparison_comparable = comparison["comparability"]["status"] == "comparable"
    exact_head = exact_head_verified(comparison)

    rules = [
        evaluate_rule(
            rule,
            measurements,
            amplifications,
            comparison_comparable,
            exact_head,
        )
        for rule in policy["rules"]
    ]

    hard_failures = sum(
        rule["mode"] == "hard" and rule["status"] == "exceeded"
        for rule in rules
    )
    hard_blocked = sum(
        rule["mode"] == "hard"
        and rule["status"] in {"unavailable", "ineligible_for_hard_gate"}
        for rule in rules
    )
    informational_exceeded = sum(
        rule["mode"] == "informational" and rule["status"] == "exceeded"
        for rule in rules
    )
    calibration_exceeded = sum(
        rule["mode"] == "calibration" and rule["status"] == "exceeded"
        for rule in rules
    )
    unavailable = sum(
        rule["status"] in {"unavailable", "ineligible_for_hard_gate"}
        for rule in rules
    )

    if not comparison_comparable or not exact_head or hard_blocked:
        status = "blocked"
    elif hard_failures:
        status = "fail"
    else:
        status = "pass"

    evaluation = {
        "schema_version": "1.0.0",
        "kind": "performance-evidence/budget-evaluation",
        "policy": {
            "id": policy["id"],
            "sha256": sha256_file(policy_path),
        },
        "comparison": {
            "candidate_evidence_hash": comparison["candidate"]["evidence_hash"],
            "candidate_source_revision": comparison["candidate"]["source_revision"],
            "baseline_evidence_hash": comparison["baseline"]["evidence_hash"],
            "baseline_source_revision": comparison["baseline"]["source_revision"],
            "comparability": comparison["comparability"]["status"],
        },
        "execution": {
            "exact_head_verified": exact_head,
            "automatic_retries": policy["execution"]["automatic_retries"],
        },
        "status": status,
        "summary": {
            "hard_failures": hard_failures,
            "hard_blocked": hard_blocked,
            "informational_exceeded": informational_exceeded,
            "calibration_exceeded": calibration_exceeded,
            "unavailable": unavailable,
        },
        "rules": rules,
    }

    evaluation_schema = load_json(EVALUATION_SCHEMA_PATH)
    Draft202012Validator.check_schema(evaluation_schema)
    validator = Draft202012Validator(
        evaluation_schema,
        format_checker=FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(evaluation),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        detail = "\n  - ".join(
            f"{format_path(list(error.absolute_path))}: {error.message}"
            for error in errors
        )
        raise RuntimeError(f"generated budget evaluation failed its contract:\n  - {detail}")

    return evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate deterministic Performance Evidence budgets without "
            "turning noisy outcome timing into hard merge authority."
        )
    )
    parser.add_argument("policy", type=Path)
    parser.add_argument("comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        evaluation = evaluate_budget(args.policy, args.comparison)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Performance Evidence budget evaluation failed: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evaluation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"Performance Evidence budget evaluation written to {args.output} "
        f"({evaluation['status']})."
    )
    return 0 if evaluation["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
