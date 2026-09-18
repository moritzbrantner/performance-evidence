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
PROFILES = ROOT / "profiles"
COMPARISON_FIXTURES = ROOT / "fixtures" / "comparison"
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


def semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    measurements = document.get("measurements", {})
    seen: dict[str, str] = {}
    total = 0

    for group in MEASUREMENT_GROUPS:
        entries = measurements.get(group, [])
        for index, measurement in enumerate(entries):
            total += 1
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
    errors.extend(semantic_errors(document))
    return errors


def profile_semantic_errors(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, measurement in enumerate(document.get("measurements", [])):
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
    revision = os.environ.get("GITHUB_SHA")
    if not revision:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()

    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    )
    return revision, dirty


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
        "version": "1.1.0",
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
    workload_paths = [
        SCHEMA_PATH,
        PROFILE_SCHEMA_PATH,
        COMPARISON_SCHEMA_PATH,
        ROOT / "scripts" / "compare_evidence.py",
        *comparison_paths,
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
            ],
            "induced_work": [
                measurement(
                    "json_documents_loaded",
                    fixture_count + len(profile_paths) + len(comparison_paths) + 3,
                    "Schemas, profiles, and fixture JSON documents loaded for the scenario.",
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

    return failures


def validate_fixtures(evidence_path: Path | None = None) -> int:
    schema = load_json(SCHEMA_PATH)
    profile_schema = load_json(PROFILE_SCHEMA_PATH)
    comparison_schema = load_json(COMPARISON_SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator.check_schema(profile_schema)
    Draft202012Validator.check_schema(comparison_schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    profile_validator = Draft202012Validator(
        profile_schema, format_checker=FormatChecker()
    )
    comparison_validator = Draft202012Validator(
        comparison_schema, format_checker=FormatChecker()
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
        measurement_entries_examined += len(document.get("measurements", []))
        errors = profile_validation_errors(profile_validator, document)
        if errors:
            failures.append(
                f"measurement profile {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    for path in valid_paths:
        document = load_json(path)
        measurement_entries_examined += sum(
            len(document.get("measurements", {}).get(group, []))
            for group in MEASUREMENT_GROUPS
        )
        errors = validation_errors(validator, document)
        if errors:
            failures.append(
                f"valid fixture {path.relative_to(ROOT)} was rejected:\n  - "
                + "\n  - ".join(errors)
            )

    for path in invalid_paths:
        document = load_json(path)
        measurement_entries_examined += sum(
            len(document.get("measurements", {}).get(group, []))
            for group in MEASUREMENT_GROUPS
        )
        errors = validation_errors(validator, document)
        if not errors:
            failures.append(
                f"invalid fixture {path.relative_to(ROOT)} unexpectedly passed validation"
            )

    failures.extend(validate_comparison_contract(validator, comparison_validator))

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
        f"{len(invalid_paths)} invalid fixtures, 1 comparison contract)."
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
