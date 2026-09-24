#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
PROFILE_SCHEMA_PATH = ROOT / "schema" / "measurement-profile.schema.json"
COMPARISON_SCHEMA_PATH = ROOT / "schema" / "performance-comparison.schema.json"
BUDGET_POLICY_SCHEMA_PATH = ROOT / "schema" / "performance-budget-policy.schema.json"
BUDGET_EVALUATION_SCHEMA_PATH = ROOT / "schema" / "performance-budget-evaluation.schema.json"
PROFILES = ROOT / "profiles"
COMPARISON_FIXTURES = ROOT / "fixtures" / "comparison"
BUDGET_FIXTURES = ROOT / "fixtures" / "budget"
VALID_FIXTURES = ROOT / "fixtures" / "valid"
INVALID_FIXTURES = ROOT / "fixtures" / "invalid"
MEASUREMENT_GROUPS = ("useful_work", "induced_work", "outcomes")
REPOSITORY_URI = "https://github.com/moritzbrantner/performance-evidence"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def format_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    return "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}" for part in parts
    )


def semantic_errors(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []

    measurements = document.get("measurements")
    if not isinstance(measurements, dict):
        return []

    errors: list[str] = []
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
                    f"{location}.name duplicates {name!r}; first declared at {previous}.name"
                )
            else:
                seen[name] = location

    if total == 0:
        errors.append("measurements must contain at least one measurement")

    return errors


def validation_errors(
    validator: Draft202012Validator, document: Any
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


def profile_semantic_errors(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []
    measurements = document.get("measurements")
    if not isinstance(measurements, list):
        return []

    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, measurement in enumerate(measurements):
        if not isinstance(measurement, dict):
            continue
        name = measurement.get("name")
        if not isinstance(name, str):
            continue
        previous = seen.get(name)
        if previous is not None:
            errors.append(
                f"$.measurements[{index}].name duplicates {name!r}; "
                f"first declared at $.measurements[{previous}].name"
            )
        else:
            seen[name] = index
    return errors


def profile_validation_errors(
    validator: Draft202012Validator, document: dict[str, Any]
) -> list[str]:
    schema_errors = sorted(
        validator.iter_errors(document),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    errors = [
        f"{format_path(list(error.absolute_path))}: {error.message}"
        for error in schema_errors
    ]
    errors.extend(profile_semantic_errors(document))
    return errors


def measurement_entry_count(document: Any) -> int:
    if not isinstance(document, dict):
        return 0
    measurements = document.get("measurements")
    if isinstance(measurements, list):
        return len(measurements)
    if not isinstance(measurements, dict):
        return 0
    return sum(
        len(entries)
        for group in MEASUREMENT_GROUPS
        if isinstance((entries := measurements.get(group)), list)
    )


def sha256_bytes(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def workload_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def source_state() -> tuple[str, bool]:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()

    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    )
    return revision, dirty


def validate_source_state() -> list[str]:
    expected = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    previous = os.environ.get("GITHUB_SHA")
    os.environ["GITHUB_SHA"] = "f" * 40
    try:
        observed, _ = source_state()
    finally:
        if previous is None:
            os.environ.pop("GITHUB_SHA", None)
        else:
            os.environ["GITHUB_SHA"] = previous

    if observed != expected:
        return [
            "source revision followed GITHUB_SHA instead of the measured checkout HEAD"
        ]
    return []


def environment_evidence() -> dict[str, Any]:
    platform_data = {
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
    }
    toolchain = {
        "python": platform.python_version(),
        "jsonschema": importlib.metadata.version("jsonschema"),
    }
    collector = {
        "name": "performance-evidence.contract-validator",
        "version": "1.2.0",
    }
    fingerprint_payload = json.dumps(
        {
            "platform": platform_data,
            "toolchain": toolchain,
            "collector": collector,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "fingerprint": sha256_bytes(fingerprint_payload),
        "platform": platform_data,
        "toolchain": toolchain,
        "collector": collector,
    }


def measurement(name: str, value: int, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": "count",
        "measurement_type": "counter",
        "description": description,
    }


def build_dogfood_evidence(
    valid_paths: list[Path],
    invalid_paths: list[Path],
    profile_paths: list[Path],
    measurement_entries_examined: int,
) -> dict[str, Any]:
    revision, dirty = source_state()
    comparison_paths = sorted(COMPARISON_FIXTURES.glob("*.json"))
    budget_paths = sorted(BUDGET_FIXTURES.glob("*.json"))
    workload_paths = [
        SCHEMA_PATH,
        PROFILE_SCHEMA_PATH,
        COMPARISON_SCHEMA_PATH,
        BUDGET_POLICY_SCHEMA_PATH,
        BUDGET_EVALUATION_SCHEMA_PATH,
        ROOT / "scripts" / "compare_evidence.py",
        ROOT / "scripts" / "evaluate_budget.py",
        *comparison_paths,
        *budget_paths,
        *profile_paths,
        *valid_paths,
        *invalid_paths,
    ]
    fixture_count = len(valid_paths) + len(invalid_paths)

    return {
        "schema_version": "1.0.0",
        "scenario": {
            "id": "performance-evidence/contract-validation",
            "description": "Validate canonical schemas, measurement profiles, and accepted/rejected fixtures.",
            "workload": {
                "id": "schema-profiles-and-fixtures-v1",
                "hash": workload_hash(workload_paths),
                "parameters": {
                    "profiles": len(profile_paths),
                    "valid_fixtures": len(valid_paths),
                    "invalid_fixtures": len(invalid_paths),
                    "budget_policies": len(budget_paths),
                },
            },
        },
        "source": {
            "repository": REPOSITORY_URI,
            "revision": revision,
            "dirty": dirty,
        },
        "environment": environment_evidence(),
        "measurements": {
            "useful_work": [
                measurement(
                    "profiles_verified",
                    len(profile_paths),
                    "Measurement profiles verified against the profile contract.",
                ),
                measurement(
                    "valid_fixtures_verified",
                    len(valid_paths),
                    "Fixtures expected to conform that were verified.",
                ),
                measurement(
                    "invalid_fixtures_rejected",
                    len(invalid_paths),
                    "Fixtures expected to fail that were rejected.",
                ),
                measurement(
                    "comparison_contracts_verified",
                    1,
                    "Comparison contract and deterministic comparison fixture verified.",
                ),
                measurement(
                    "budget_contracts_verified",
                    1,
                    "Budget policy/evaluation contracts and deterministic CI semantics verified.",
                ),
            ],
            "induced_work": [
                measurement(
                    "json_documents_loaded",
                    fixture_count
                    + len(profile_paths)
                    + len(comparison_paths)
                    + len(budget_paths)
                    + 5,
                    "Schemas, profiles, policies, and fixture JSON documents loaded for the scenario.",
                ),
                measurement(
                    "profile_validations",
                    len(profile_paths),
                    "Measurement profiles passed through structural and semantic validation.",
                ),
                measurement(
                    "fixture_validations",
                    fixture_count,
                    "Fixture documents passed through schema and semantic validation.",
                ),
                measurement(
                    "comparison_fixture_validations",
                    len(comparison_paths),
                    "Comparison inputs and expected output checked for deterministic semantics.",
                ),
                measurement(
                    "budget_fixture_validations",
                    len(budget_paths),
                    "Budget policies exercised across pass, failure, and blocked CI semantics.",
                ),
                measurement(
                    "measurement_entries_examined",
                    measurement_entries_examined,
                    "Measurement entries inspected by semantic validation.",
                ),
            ],
            "outcomes": [
                measurement(
                    "validation_failures",
                    0,
                    "Unexpected profile, fixture, or contract validation failures.",
                )
            ],
        },
    }


def write_evidence(
    output_path: Path,
    validator: Draft202012Validator,
    evidence: dict[str, Any],
) -> None:
    errors = validation_errors(validator, evidence)
    if errors:
        raise RuntimeError(
            "dogfood evidence failed its own contract:\n  - " + "\n  - ".join(errors)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )



def validate_comparison_contract(
    evidence_validator: Draft202012Validator,
    comparison_validator: Draft202012Validator,
) -> list[str]:
    failures: list[str] = []
    baseline_path = COMPARISON_FIXTURES / "baseline.json"
    candidate_path = COMPARISON_FIXTURES / "candidate.json"
    expected_path = COMPARISON_FIXTURES / "expected.json"

    for path in (baseline_path, candidate_path):
        if not path.is_file():
            failures.append(f"missing comparison fixture {path.relative_to(ROOT)}")
            continue
        errors = validation_errors(evidence_validator, load_json(path))
        if errors:
            failures.append(
                f"comparison evidence fixture {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    if not expected_path.is_file():
        failures.append(f"missing comparison fixture {expected_path.relative_to(ROOT)}")
        return failures

    expected = load_json(expected_path)
    schema_errors = sorted(
        comparison_validator.iter_errors(expected),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if schema_errors:
        failures.append(
            f"comparison fixture {expected_path.relative_to(ROOT)} was rejected:\n  - "
            + "\n  - ".join(
                f"{format_path(list(error.absolute_path))}: {error.message}"
                for error in schema_errors
            )
        )
        return failures

    if failures:
        return failures

    with tempfile.TemporaryDirectory() as temporary_directory:
        output_path = Path(temporary_directory) / "comparison.json"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "compare_evidence.py"),
            str(baseline_path),
            str(candidate_path),
            "--expected-candidate-revision",
            "1111111111111111111111111111111111111111",
            "--output",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(
                "comparison fixture execution failed: "
                + (result.stderr.strip() or result.stdout.strip())
            )
            return failures

        actual = load_json(output_path)
        if actual != expected:
            failures.append(
                "comparison fixture output did not match fixtures/comparison/expected.json"
            )

        amplification_path = Path(temporary_directory) / "amplifications.json"
        amplification_command = [
            sys.executable,
            str(ROOT / "scripts" / "compare_evidence.py"),
            str(baseline_path),
            str(candidate_path),
            "--expected-candidate-revision",
            "1111111111111111111111111111111111111111",
            "--amplification",
            "physics.body_visits_per_changed_body=physics.body_visits,physics.changed_bodies",
            "--amplification",
            "memory.bytes_per_changed_body=memory.bytes_copied,physics.changed_bodies",
            "--amplification",
            "physics.visits_per_copied_byte=physics.body_visits,memory.bytes_copied",
            "--amplification",
            "cpu.instructions_per_changed_body=cpu.instructions,physics.changed_bodies",
            "--amplification",
            "physics.only_baseline_per_changed_body=physics.only_baseline,physics.changed_bodies",
            "--output",
            str(amplification_path),
        ]
        amplification = subprocess.run(
            amplification_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if amplification.returncode != 0:
            failures.append(
                "amplification comparison fixture execution failed: "
                + (amplification.stderr.strip() or amplification.stdout.strip())
            )
            return failures

        amplification_document = load_json(amplification_path)
        expected_amplifications = [
            {
                "name": "physics.body_visits_per_changed_body",
                "numerator": "physics.body_visits",
                "denominator": "physics.changed_bodies",
                "status": "comparable",
                "baseline": {
                    "status": "defined",
                    "numerator_value": 126,
                    "denominator_value": 8,
                    "value": 15.75,
                },
                "candidate": {
                    "status": "defined",
                    "numerator_value": 100,
                    "denominator_value": 8,
                    "value": 12.5,
                },
                "absolute_delta": -3.25,
                "relative_delta": {
                    "status": "defined",
                    "value": -0.20634920634920634,
                },
            },
            {
                "name": "memory.bytes_per_changed_body",
                "numerator": "memory.bytes_copied",
                "denominator": "physics.changed_bodies",
                "status": "comparable",
                "baseline": {
                    "status": "defined",
                    "numerator_value": 0,
                    "denominator_value": 8,
                    "value": 0.0,
                },
                "candidate": {
                    "status": "defined",
                    "numerator_value": 1024,
                    "denominator_value": 8,
                    "value": 128.0,
                },
                "absolute_delta": 128.0,
                "relative_delta": {
                    "status": "undefined_zero_baseline",
                    "value": None,
                },
            },
            {
                "name": "physics.visits_per_copied_byte",
                "numerator": "physics.body_visits",
                "denominator": "memory.bytes_copied",
                "status": "undefined_zero_denominator",
                "baseline": {
                    "status": "undefined_zero_denominator",
                    "numerator_value": 126,
                    "denominator_value": 0,
                    "value": None,
                },
                "candidate": {
                    "status": "defined",
                    "numerator_value": 100,
                    "denominator_value": 1024,
                    "value": 0.09765625,
                },
                "absolute_delta": None,
                "relative_delta": {
                    "status": "unavailable",
                    "value": None,
                },
            },
            {
                "name": "cpu.instructions_per_changed_body",
                "numerator": "cpu.instructions",
                "denominator": "physics.changed_bodies",
                "status": "incompatible_definition",
                "baseline": {
                    "status": "incompatible_definition",
                    "numerator_value": 1000,
                    "denominator_value": 8,
                    "value": None,
                },
                "candidate": {
                    "status": "incompatible_definition",
                    "numerator_value": 900,
                    "denominator_value": 8,
                    "value": None,
                },
                "absolute_delta": None,
                "relative_delta": {
                    "status": "unavailable",
                    "value": None,
                },
            },
            {
                "name": "physics.only_baseline_per_changed_body",
                "numerator": "physics.only_baseline",
                "denominator": "physics.changed_bodies",
                "status": "missing_measurement",
                "baseline": {
                    "status": "defined",
                    "numerator_value": 10,
                    "denominator_value": 8,
                    "value": 1.25,
                },
                "candidate": {
                    "status": "missing_numerator",
                    "numerator_value": None,
                    "denominator_value": 8,
                    "value": None,
                },
                "absolute_delta": None,
                "relative_delta": {
                    "status": "unavailable",
                    "value": None,
                },
            },
        ]
        if amplification_document.get("amplifications") != expected_amplifications:
            failures.append("work amplification fixture produced unexpected ratios")
        if amplification_document["measurements"] != expected["measurements"]:
            failures.append("work amplification derivation changed raw measurement comparisons")

        mismatch_path = Path(temporary_directory) / "mismatch.json"
        mismatch_command = [
            sys.executable,
            str(ROOT / "scripts" / "compare_evidence.py"),
            str(baseline_path),
            str(candidate_path),
            "--expected-candidate-revision",
            "ffffffffffffffffffffffffffffffffffffffff",
            "--output",
            str(mismatch_path),
        ]
        mismatch = subprocess.run(
            mismatch_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if mismatch.returncode != 0:
            failures.append(
                "incomparable comparison fixture execution failed: "
                + (mismatch.stderr.strip() or mismatch.stdout.strip())
            )
            return failures

        mismatch_document = load_json(mismatch_path)
        if mismatch_document["comparability"] != {
            "status": "incomparable",
            "reasons": ["candidate_revision_mismatch"],
            "expected_candidate_revision": "ffffffffffffffffffffffffffffffffffffffff",
        }:
            failures.append(
                "candidate revision mismatch did not fail closed with the expected reason"
            )
        if any(
            entry["status"] != "scenario_incomparable"
            or entry["absolute_delta"] is not None
            or entry["relative_delta"] != {"status": "unavailable", "value": None}
            for entry in mismatch_document["measurements"]
        ):
            failures.append(
                "incomparable scenario unexpectedly exposed measurement deltas"
            )

        cross_repository_candidate = load_json(candidate_path)
        cross_repository_candidate["source"]["repository"] = (
            "https://github.com/example/other-repository"
        )
        cross_repository_candidate_path = (
            Path(temporary_directory) / "cross-repository-candidate.json"
        )
        cross_repository_candidate_path.write_text(
            json.dumps(cross_repository_candidate, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cross_repository_path = Path(temporary_directory) / "cross-repository.json"
        cross_repository = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "compare_evidence.py"),
                str(baseline_path),
                str(cross_repository_candidate_path),
                "--expected-candidate-revision",
                "1111111111111111111111111111111111111111",
                "--output",
                str(cross_repository_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if cross_repository.returncode != 0:
            failures.append(
                "cross-repository comparison fixture execution failed: "
                + (cross_repository.stderr.strip() or cross_repository.stdout.strip())
            )
        else:
            cross_repository_document = load_json(cross_repository_path)
            if cross_repository_document["comparability"]["reasons"] != [
                "repository_mismatch"
            ]:
                failures.append("cross-repository evidence was not rejected explicitly")
            if any(
                entry["status"] != "scenario_incomparable"
                for entry in cross_repository_document["measurements"]
            ):
                failures.append(
                    "cross-repository evidence unexpectedly exposed comparable measurements"
                )

    return failures



def validate_budget_contract(
    policy_validator: Draft202012Validator,
    evaluation_validator: Draft202012Validator,
) -> list[str]:
    failures: list[str] = []
    baseline_path = COMPARISON_FIXTURES / "baseline.json"
    candidate_path = COMPARISON_FIXTURES / "candidate.json"
    policies = {
        "pass": BUDGET_FIXTURES / "policy-pass.json",
        "fail": BUDGET_FIXTURES / "policy-fail.json",
        "hard_timing": BUDGET_FIXTURES / "policy-hard-timing.json",
        "zero_baseline": BUDGET_FIXTURES / "policy-zero-baseline-relative.json",
    }

    for label, path in policies.items():
        if not path.is_file():
            failures.append(f"missing budget fixture {path.relative_to(ROOT)}")
            continue
        errors = sorted(
            policy_validator.iter_errors(load_json(path)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if errors:
            failures.append(
                f"budget fixture {label} was rejected:\n  - "
                + "\n  - ".join(
                    f"{format_path(list(error.absolute_path))}: {error.message}"
                    for error in errors
                )
            )
    if failures:
        return failures

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        comparison_path = temporary_root / "comparison.json"
        comparison_command = [
            sys.executable,
            str(ROOT / "scripts" / "compare_evidence.py"),
            str(baseline_path),
            str(candidate_path),
            "--expected-candidate-revision",
            "1111111111111111111111111111111111111111",
            "--amplification",
            "physics.body_visits_per_changed_body=physics.body_visits,physics.changed_bodies",
            "--output",
            str(comparison_path),
        ]
        comparison = subprocess.run(
            comparison_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if comparison.returncode != 0:
            failures.append(
                "budget fixture comparison failed: "
                + (comparison.stderr.strip() or comparison.stdout.strip())
            )
            return failures

        def evaluate(
            label: str,
            policy_path: Path,
            expected_exit: int,
        ) -> dict[str, Any] | None:
            output_path = temporary_root / f"{label}.json"
            command = [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_budget.py"),
                str(policy_path),
                str(comparison_path),
                "--output",
                str(output_path),
            ]
            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode != expected_exit:
                failures.append(
                    f"budget fixture {label} returned {result.returncode}, "
                    f"expected {expected_exit}: "
                    + (result.stderr.strip() or result.stdout.strip())
                )
                return None
            if not output_path.is_file():
                failures.append(f"budget fixture {label} did not write an evaluation")
                return None
            document = load_json(output_path)
            errors = sorted(
                evaluation_validator.iter_errors(document),
                key=lambda error: tuple(str(part) for part in error.absolute_path),
            )
            if errors:
                failures.append(
                    f"budget evaluation {label} was rejected:\n  - "
                    + "\n  - ".join(
                        f"{format_path(list(error.absolute_path))}: {error.message}"
                        for error in errors
                    )
                )
                return None
            return document

        passing = evaluate("pass", policies["pass"], 0)
        if passing is not None:
            if passing["status"] != "pass":
                failures.append("passing budget fixture did not produce status=pass")
            if passing["execution"] != {
                "exact_head_verified": True,
                "automatic_retries": 0,
            }:
                failures.append("passing budget fixture lost exact-head/non-retry semantics")
            if passing["summary"] != {
                "hard_failures": 0,
                "hard_blocked": 0,
                "informational_exceeded": 1,
                "calibration_exceeded": 1,
                "unavailable": 0,
            }:
                failures.append("passing budget fixture produced an unexpected summary")

        failing = evaluate("fail", policies["fail"], 2)
        if failing is not None and (
            failing["status"] != "fail"
            or failing["summary"]["hard_failures"] != 1
            or failing["rules"][0]["status"] != "exceeded"
        ):
            failures.append("hard regression budget did not fail closed")

        hard_timing = evaluate("hard-timing", policies["hard_timing"], 2)
        if hard_timing is not None and (
            hard_timing["status"] != "blocked"
            or hard_timing["summary"]["hard_blocked"] != 1
            or hard_timing["rules"][0]["status"] != "ineligible_for_hard_gate"
        ):
            failures.append("wall-clock hard gate was not blocked")

        zero_baseline = evaluate("zero-baseline", policies["zero_baseline"], 2)
        if zero_baseline is not None and (
            zero_baseline["status"] != "blocked"
            or zero_baseline["summary"]["hard_blocked"] != 1
            or zero_baseline["rules"][0]["status"] != "unavailable"
        ):
            failures.append("zero-baseline relative hard budget did not remain unavailable")

        original_comparison_path = comparison_path
        mismatch_path = temporary_root / "mismatch-comparison.json"
        mismatch_command = [
            sys.executable,
            str(ROOT / "scripts" / "compare_evidence.py"),
            str(baseline_path),
            str(candidate_path),
            "--expected-candidate-revision",
            "ffffffffffffffffffffffffffffffffffffffff",
            "--output",
            str(mismatch_path),
        ]
        mismatch = subprocess.run(
            mismatch_command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if mismatch.returncode != 0:
            failures.append(
                "budget mismatch comparison failed: "
                + (mismatch.stderr.strip() or mismatch.stdout.strip())
            )
        else:
            comparison_path = mismatch_path
            mismatched = evaluate("mismatched-head", policies["pass"], 2)
            comparison_path = original_comparison_path
            if mismatched is not None and (
                mismatched["status"] != "blocked"
                or mismatched["execution"]["exact_head_verified"]
            ):
                failures.append("mismatched authoritative evidence did not block budgets")

        tampered_comparison = load_json(original_comparison_path)
        body_visits = next(
            entry
            for entry in tampered_comparison["measurements"]
            if entry["name"] == "physics.body_visits"
        )
        body_visits["candidate"]["value"] = 1000
        tampered_path = temporary_root / "tampered-comparison.json"
        tampered_path.write_text(
            json.dumps(tampered_comparison, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_output = temporary_root / "tampered-evaluation.json"
        tampered = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_budget.py"),
                str(policies["pass"]),
                str(tampered_path),
                "--output",
                str(tampered_output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if tampered.returncode != 1 or tampered_output.exists():
            failures.append(
                "internally contradictory comparison was not rejected before budgeting"
            )

        malformed_policy = load_json(policies["pass"])
        malformed_policy["rules"].append(dict(malformed_policy["rules"][0]))
        malformed_path = temporary_root / "duplicate-rule-policy.json"
        malformed_path.write_text(
            json.dumps(malformed_policy, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        malformed_output = temporary_root / "malformed-evaluation.json"
        malformed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_budget.py"),
                str(malformed_path),
                str(original_comparison_path),
                "--output",
                str(malformed_output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if malformed.returncode != 1 or malformed_output.exists():
            failures.append("malformed budget policy did not fail closed before evaluation")

    return failures


def validate_fixtures(evidence_path: Path | None = None) -> int:
    schema = load_json(SCHEMA_PATH)
    profile_schema = load_json(PROFILE_SCHEMA_PATH)
    comparison_schema = load_json(COMPARISON_SCHEMA_PATH)
    budget_policy_schema = load_json(BUDGET_POLICY_SCHEMA_PATH)
    budget_evaluation_schema = load_json(BUDGET_EVALUATION_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(profile_schema)
    Draft202012Validator.check_schema(comparison_schema)
    Draft202012Validator.check_schema(budget_policy_schema)
    Draft202012Validator.check_schema(budget_evaluation_schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    profile_validator = Draft202012Validator(
        profile_schema, format_checker=FormatChecker()
    )
    comparison_validator = Draft202012Validator(
        comparison_schema, format_checker=FormatChecker()
    )
    budget_policy_validator = Draft202012Validator(
        budget_policy_schema, format_checker=FormatChecker()
    )
    budget_evaluation_validator = Draft202012Validator(
        budget_evaluation_schema, format_checker=FormatChecker()
    )

    failures: list[str] = []
    measurement_entries_examined = 0

    profile_paths = sorted(PROFILES.glob("*.json"))
    valid_paths = sorted(VALID_FIXTURES.glob("*.json"))
    invalid_paths = sorted(INVALID_FIXTURES.glob("*.json"))

    if not profile_paths:
        failures.append("no measurement profiles found")
    if not valid_paths:
        failures.append("no valid fixtures found")
    if not invalid_paths:
        failures.append("no invalid fixtures found")

    for path in profile_paths:
        document = load_json(path)
        measurement_entries_examined += measurement_entry_count(document)
        errors = profile_validation_errors(profile_validator, document)
        if errors:
            failures.append(
                f"measurement profile {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    for path in valid_paths:
        document = load_json(path)
        measurement_entries_examined += measurement_entry_count(document)
        errors = validation_errors(validator, document)
        if errors:
            failures.append(
                f"valid fixture {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    for path in invalid_paths:
        document = load_json(path)
        measurement_entries_examined += measurement_entry_count(document)
        errors = validation_errors(validator, document)
        if not errors:
            failures.append(
                f"invalid fixture {path.relative_to(ROOT)} unexpectedly passed validation"
            )

    if valid_paths:
        malformed_measurements = json.loads(json.dumps(load_json(valid_paths[0])))
        malformed_measurements["measurements"] = None
        try:
            malformed_errors = validation_errors(validator, malformed_measurements)
        except (AttributeError, TypeError) as error:
            failures.append(
                "structurally malformed measurements crashed semantic validation: "
                + str(error)
            )
        else:
            if not malformed_errors:
                failures.append(
                    "structurally malformed measurements unexpectedly passed validation"
                )

    failures.extend(validate_source_state())
    failures.extend(validate_comparison_contract(validator, comparison_validator))
    failures.extend(
        validate_budget_contract(
            budget_policy_validator,
            budget_evaluation_validator,
        )
    )

    if failures:
        print("Performance Evidence contract validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    if evidence_path is not None:
        try:
            evidence = build_dogfood_evidence(
                valid_paths,
                invalid_paths,
                profile_paths,
                measurement_entries_examined,
            )
            write_evidence(evidence_path, validator, evidence)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
            print(f"Performance Evidence dogfood emission failed: {error}", file=sys.stderr)
            return 1

    print(
        "Performance Evidence contract validation passed "
        f"({len(profile_paths)} profiles, {len(valid_paths)} valid, "
        f"{len(invalid_paths)} invalid fixtures, 1 comparison contract, "
        "1 budget policy/evaluation contract)."
    )
    if evidence_path is not None:
        print(f"Dogfood evidence written to {evidence_path}.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Performance Evidence schemas, profiles, and fixtures."
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        help="Write dogfood performance evidence for the validation scenario.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(validate_fixtures(args.evidence))
