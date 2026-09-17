#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


COLLECTOR_NAME = "performance-evidence.agent-loop-efficiency-adapter"
COLLECTOR_VERSION = "1.0.0"
SCENARIO_ID = "agent/implementation-attempt"
WORKLOAD_ID = "repository-task-v1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def repository_uri(repository: Any) -> str | None:
    if not isinstance(repository, str) or not repository:
        return None
    if repository.startswith("https://") or repository.startswith("http://"):
        return repository
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return f"https://github.com/{repository}"
    return None


def measurement(
    name: str,
    value: int | float,
    unit: str,
    measurement_type: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "measurement_type": measurement_type,
    }


def optional_measurement(
    target: list[dict[str, Any]],
    source: Any,
    name: str,
    unit: str,
    measurement_type: str,
) -> None:
    if isinstance(source, bool) or not isinstance(source, (int, float)) or source < 0:
        return
    target.append(measurement(name, source, unit, measurement_type))


def workload_identity(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": attempt.get("taskId"),
        "project_id": attempt.get("projectId"),
        "repository": attempt.get("repository"),
        "baseline_revision": attempt.get("baselineSha"),
    }


def environment_identity(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment": attempt.get("environment"),
        "provider": attempt.get("provider"),
        "model": attempt.get("model"),
    }


def convert_attempt(attempt: dict[str, Any], source_dirty: bool) -> dict[str, Any]:
    baseline_sha = attempt.get("baselineSha")
    task_id = attempt.get("taskId")
    run_id = attempt.get("runId")
    project_id = attempt.get("projectId")
    provider = attempt.get("provider")
    attempt_number = attempt.get("attemptNumber")

    required = {
        "taskId": task_id,
        "runId": run_id,
        "projectId": project_id,
        "baselineSha": baseline_sha,
        "provider": provider,
        "attemptNumber": attempt_number,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError("attempt is missing required fields: " + ", ".join(missing))

    useful_work = [
        measurement(
            "agent.candidate_produced",
            1 if attempt.get("candidateSha") else 0,
            "count",
            "counter",
        )
    ]
    induced_work: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []

    usage = attempt.get("usage")
    if isinstance(usage, dict):
        optional_measurement(
            induced_work,
            usage.get("inputTokens"),
            "agent.input_tokens",
            "token",
            "counter",
        )
        optional_measurement(
            induced_work,
            usage.get("outputTokens"),
            "agent.output_tokens",
            "token",
            "counter",
        )
        optional_measurement(
            induced_work,
            usage.get("cachedInputTokens"),
            "agent.cached_input_tokens",
            "token",
            "counter",
        )
        optional_measurement(
            outcomes,
            usage.get("costUsd"),
            "agent.cost",
            "usd",
            "gauge",
        )

    optional_measurement(
        outcomes,
        attempt.get("executionMs"),
        "agent.execution_time",
        "ms",
        "duration",
    )
    optional_measurement(
        outcomes,
        attempt.get("deterministicTimeToGreenMs"),
        "agent.deterministic_time_to_green",
        "ms",
        "duration",
    )

    workload = workload_identity(attempt)
    environment = environment_identity(attempt)
    extension = {
        "task_id": task_id,
        "run_id": run_id,
        "project_id": project_id,
        "provider": provider,
        "attempt_number": attempt_number,
        "resumed_provider_session": bool(attempt.get("resumedProviderSession", False)),
    }
    for source_key, target_key in (
        ("model", "model"),
        ("outcome", "outcome"),
        ("failureReason", "failure_reason"),
        ("escalationReason", "escalation_reason"),
        ("ciRunIds", "ci_run_ids"),
        ("candidateSha", "candidate_revision"),
    ):
        value = attempt.get(source_key)
        if value is not None:
            extension[target_key] = value

    source: dict[str, Any] = {
        "revision": str(baseline_sha),
        "dirty": source_dirty,
    }
    uri = repository_uri(attempt.get("repository"))
    if uri is not None:
        source["repository"] = uri

    toolchain = {"agent_provider": str(provider)}
    if attempt.get("model") is not None:
        toolchain["agent_model"] = str(attempt["model"])

    return {
        "schema_version": "1.0.0",
        "scenario": {
            "id": SCENARIO_ID,
            "description": "One coding-agent implementation attempt measured for computational cost and time-to-green.",
            "workload": {
                "id": WORKLOAD_ID,
                "hash": sha256_value(workload),
                "parameters": workload,
            },
        },
        "source": source,
        "environment": {
            "fingerprint": sha256_value(environment),
            "toolchain": toolchain,
            "collector": {
                "name": COLLECTOR_NAME,
                "version": COLLECTOR_VERSION,
            },
        },
        "measurements": {
            "useful_work": useful_work,
            "induced_work": induced_work,
            "outcomes": outcomes,
        },
        "extensions": {
            "agent.execution": extension,
        },
    }


def output_name(attempt: dict[str, Any]) -> str:
    run_id = attempt.get("runId")
    attempt_number = attempt.get("attemptNumber")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("attempt is missing runId")
    if not isinstance(attempt_number, int) or attempt_number < 0:
        raise ValueError("attempt has invalid attemptNumber")
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]", "-", run_id)
    return f"{safe_run_id}.attempt-{attempt_number}.performance-evidence.json"


def convert_report(report: dict[str, Any], source_dirty: bool) -> list[tuple[str, dict[str, Any]]]:
    attempts = report.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError("efficiency report must contain an attempts array")

    converted: list[tuple[str, dict[str, Any]]] = []
    seen_names: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("every attempt must be an object")
        name = output_name(attempt)
        if name in seen_names:
            raise ValueError(f"duplicate output identity: {name}")
        seen_names.add(name)
        converted.append((name, convert_attempt(attempt, source_dirty)))
    return converted


def parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert agent-loop efficiency attempts into canonical Performance Evidence artifacts."
    )
    parser.add_argument("report", type=Path, help="agent-loop-efficiency JSON report")
    parser.add_argument("output_dir", type=Path, help="directory for per-attempt evidence")
    parser.add_argument(
        "--source-dirty",
        required=True,
        type=parse_bool,
        help="whether the attempt source baseline was dirty; pass false only when exact clean-baseline execution is established",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("efficiency report root must be an object")
        converted = convert_report(report, args.source_dirty)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, evidence in converted:
            (args.output_dir / name).write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"agent-loop efficiency conversion failed: {error}", file=sys.stderr)
        return 1

    print(f"Wrote {len(converted)} Performance Evidence artifact(s) to {args.output_dir}.")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
