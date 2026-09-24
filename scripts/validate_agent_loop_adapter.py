#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from convert_agent_loop_efficiency import convert_report, repository_uri
from validate_schema import validation_errors


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "agent-loop-efficiency"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"
EXPECTED_NAME = "018f5d43-4d1c-7fd5-aed5-d451fd71c110.attempt-1.performance-evidence.json"
EXPECTED_REPOSITORY = "https://github.com/moritzbrantner/physics-engine"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_repository_uris() -> None:
    for repository in (
        "moritzbrantner/physics-engine",
        "https://github.com/moritzbrantner/physics-engine.git",
        "http://github.com/moritzbrantner/physics-engine.git",
        "git://github.com/moritzbrantner/physics-engine.git",
        "git@github.com:moritzbrantner/physics-engine.git",
        "ssh://git@github.com/moritzbrantner/physics-engine.git",
    ):
        actual = repository_uri(repository)
        if actual != EXPECTED_REPOSITORY:
            raise ValueError(
                f"repository URI normalization mismatch for {repository!r}: {actual!r}"
            )


def expect_value_error(action, expected_fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if expected_fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {expected_fragment!r}")


def validate_repository_identity_normalization(report: dict) -> None:
    baseline = convert_report(report, source_dirty=False)[0][1]
    expected_hash = baseline["scenario"]["workload"]["hash"]
    for repository in (
        "moritzbrantner/physics-engine",
        "https://github.com/moritzbrantner/physics-engine.git",
        "http://github.com/moritzbrantner/physics-engine.git",
        "git://github.com/moritzbrantner/physics-engine.git",
        "git@github.com:moritzbrantner/physics-engine.git",
        "ssh://git@github.com/moritzbrantner/physics-engine.git",
    ):
        variant = copy.deepcopy(report)
        variant["attempts"][0]["repository"] = repository
        evidence = convert_report(variant, source_dirty=False)[0][1]
        if evidence["source"].get("repository") != EXPECTED_REPOSITORY:
            raise ValueError("repository normalization changed source provenance")
        if evidence["scenario"]["workload"]["parameters"]["repository"] != EXPECTED_REPOSITORY:
            raise ValueError("repository normalization was not applied to workload identity")
        if evidence["scenario"]["workload"]["hash"] != expected_hash:
            raise ValueError("equivalent repository spellings changed workload identity")


def validate_routing_comparability(report: dict) -> None:
    baseline = convert_report(report, source_dirty=False)[0][1]
    variant = copy.deepcopy(report)
    attempt = variant["attempts"][0]
    attempt["provider"] = "other-provider"
    attempt["model"] = "other-model"
    routed = convert_report(variant, source_dirty=False)[0][1]

    if (
        routed["scenario"]["workload"]["hash"]
        != baseline["scenario"]["workload"]["hash"]
    ):
        raise ValueError("provider/model routing changed workload identity")
    if (
        routed["environment"]["fingerprint"]
        != baseline["environment"]["fingerprint"]
    ):
        raise ValueError("provider/model routing changed execution-environment identity")
    extension = routed["extensions"]["agent.execution"]
    if extension.get("provider") != "other-provider" or extension.get("model") != "other-model":
        raise ValueError("provider/model routing metadata was not preserved")


def validate_malformed_telemetry_rejected(report: dict) -> None:
    cases = (
        ("agent.input_tokens", ("usage", "inputTokens"), -1),
        ("usage", ("usage",), "not-an-object"),
        ("baselineSha", ("baselineSha",), 123),
        ("candidateSha", ("candidateSha",), 123),
        ("resumedProviderSession", ("resumedProviderSession",), "false"),
        ("attemptNumber", ("attemptNumber",), True),
    )
    for expected_fragment, path, value in cases:
        invalid = copy.deepcopy(report)
        target = invalid["attempts"][0]
        if len(path) == 2:
            target[path[0]][path[1]] = value
        else:
            target[path[0]] = value
        expect_value_error(
            lambda invalid=invalid: convert_report(invalid, source_dirty=False),
            expected_fragment,
        )

    missing_repository = copy.deepcopy(report)
    missing_repository["attempts"][0].pop("repository")
    expect_value_error(
        lambda: convert_report(missing_repository, source_dirty=False),
        "repository",
    )


def validate_attempt_identity_compatibility(report: dict) -> None:
    legacy_report = copy.deepcopy(report)
    legacy_attempt = legacy_report["attempts"][0]
    expected_run_id = legacy_attempt["runId"]
    legacy_attempt.pop("attemptId")
    legacy_converted = convert_report(legacy_report, source_dirty=False)
    legacy_extension = legacy_converted[0][1]["extensions"]["agent.execution"]
    if "attempt_id" in legacy_extension:
        raise ValueError("historical report without attemptId unexpectedly emitted attempt_id")
    if legacy_extension.get("run_id") != expected_run_id:
        raise ValueError("historical report lost run correlation while omitting attemptId")

    invalid_report = copy.deepcopy(report)
    invalid_report["attempts"][0]["attemptId"] = ""
    try:
        convert_report(invalid_report, source_dirty=False)
    except ValueError as error:
        if "attemptId" not in str(error):
            raise
    else:
        raise ValueError("empty attemptId was accepted")


def main() -> int:
    try:
        validate_repository_uris()
        report = load_json(FIXTURE_DIR / "report.json")
        expected = load_json(FIXTURE_DIR / "expected.json")
        converted = convert_report(report, source_dirty=False)
        if len(converted) != 1:
            raise ValueError(f"expected one converted attempt, got {len(converted)}")
        name, actual = converted[0]
        if name != EXPECTED_NAME:
            raise ValueError(f"unexpected output name: {name}")
        if actual != expected:
            print("Agent-loop adapter fixture mismatch.", file=sys.stderr)
            print(
                json.dumps(
                    {"expected": expected, "actual": actual}, indent=2, sort_keys=True
                ),
                file=sys.stderr,
            )
            return 1

        validate_repository_identity_normalization(report)
        validate_routing_comparability(report)
        validate_malformed_telemetry_rejected(report)
        validate_attempt_identity_compatibility(report)

        schema = load_json(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = validation_errors(validator, actual)
        if errors:
            print("Converted agent-loop evidence violates canonical contract:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Agent-loop adapter validation failed: {error}", file=sys.stderr)
        return 1

    print("Agent-loop efficiency adapter validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
