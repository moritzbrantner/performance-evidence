#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import summarize_agent_evidence
from summarize_agent_evidence import summarize_documents


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "agent-loop-efficiency" / "expected.json"


def load_fixture() -> dict:
    with FIXTURE.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("agent evidence fixture must be an object")
    return value


def remove_measurement(document: dict, name: str) -> None:
    measurements = document["measurements"]
    for group in ("useful_work", "induced_work", "outcomes"):
        measurements[group] = [
            entry for entry in measurements[group] if entry.get("name") != name
        ]


def set_measurement(document: dict, name: str, value: int | float) -> None:
    for group in ("useful_work", "induced_work", "outcomes"):
        for entry in document["measurements"][group]:
            if entry.get("name") == name:
                entry["value"] = value
                return
    raise ValueError(f"fixture does not contain {name}")


def distinct_attempts(document: dict, count: int) -> list[dict]:
    result: list[dict] = []
    for index in range(count):
        item = copy.deepcopy(document)
        extension = item["extensions"]["agent.execution"]
        extension["attempt_id"] = f"scaling-attempt-{index + 1}"
        extension["run_id"] = f"scaling-run-{index + 1}"
        extension["attempt_number"] = 1
        result.append(item)
    return result


def expect_value_error(action, expected_fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if expected_fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {expected_fragment!r}")


def main() -> int:
    try:
        first = load_fixture()
        second = copy.deepcopy(first)
        second_extension = second["extensions"]["agent.execution"]
        second_extension["run_id"] = "018f5d43-4d1c-7fd5-aed5-d451fd71c111"
        second_extension["attempt_id"] = "018f5d43-4d1c-7fd5-aed5-d451fd71c111-attempt-2"
        second_extension["attempt_number"] = 2
        second_extension["model"] = "gpt-5.6-pro"
        second_extension["outcome"] = "failed"
        second_extension["escalation_reason"] = "environment"
        set_measurement(second, "agent.candidate_produced", 0)
        set_measurement(second, "agent.input_tokens", 100)
        set_measurement(second, "agent.output_tokens", 20)
        set_measurement(second, "agent.execution_time", 2000)
        remove_measurement(second, "agent.cached_input_tokens")
        remove_measurement(second, "agent.cost")
        remove_measurement(second, "agent.deterministic_time_to_green")

        rollup = summarize_documents([first, second])
        summary = rollup["summary"]
        if summary["attempt_count"] != 2 or summary["candidate_count"] != 1:
            raise ValueError("attempt/candidate aggregation is incorrect")
        if summary["telemetry_coverage"]["cost_usd"] != 1:
            raise ValueError("missing cost telemetry was not preserved as missing")
        if summary["telemetry_coverage"]["cached_input_tokens"] != 1:
            raise ValueError("missing cached-token telemetry was not preserved as missing")
        if summary["telemetry_coverage"]["deterministic_time_to_green_ms"] != 1:
            raise ValueError("missing time-to-green telemetry was not preserved as missing")
        if summary["model_counts"].get("gpt-5.6-pro") != 1:
            raise ValueError("model aggregation is incorrect")
        if summary["outcome_counts"].get("failed") != 1:
            raise ValueError("outcome aggregation is incorrect")
        if summary["escalation_reason_counts"].get("environment") != 1:
            raise ValueError("escalation aggregation is incorrect")

        reversed_rollup = summarize_documents([second, first])
        if rollup["input_digest"] != reversed_rollup["input_digest"]:
            raise ValueError("input digest must be independent of file traversal order")
        if rollup["summary"] != reversed_rollup["summary"]:
            raise ValueError("rollup summary must be independent of file traversal order")

        duplicate_rollup = summarize_documents([first, copy.deepcopy(first)])
        if duplicate_rollup["summary"]["attempt_count"] != 1:
            raise ValueError("duplicate attempt evidence inflated attempt_count")
        if duplicate_rollup["summary"]["observed_totals"] != summarize_documents([first])["summary"]["observed_totals"]:
            raise ValueError("duplicate attempt evidence inflated observed totals")
        if duplicate_rollup["work"]["duplicate_documents_ignored"] != 1:
            raise ValueError("duplicate attempt evidence was not reported as ignored")

        conflicting = copy.deepcopy(first)
        conflicting["extensions"]["agent.execution"]["model"] = "conflicting-model"
        expect_value_error(
            lambda: summarize_documents([first, conflicting]),
            "conflicting evidence for the same agent attempt identity",
        )

        # Deterministic cost smoke: work accounting must scale exactly with input size.
        # This avoids a brittle wall-clock CI budget while catching accidental rescans.
        entries_per_document = sum(
            len(first["measurements"][group])
            for group in ("useful_work", "induced_work", "outcomes")
        )
        original_canonical_json = summarize_agent_evidence.canonical_json
        serialization_count = 0

        def counted_canonical_json(value):
            nonlocal serialization_count
            serialization_count += 1
            return original_canonical_json(value)

        summarize_agent_evidence.canonical_json = counted_canonical_json
        try:
            thousand = summarize_documents(distinct_attempts(first, 1000))
            two_thousand = summarize_documents(distinct_attempts(first, 2000))
        finally:
            summarize_agent_evidence.canonical_json = original_canonical_json

        if serialization_count != 3000:
            raise ValueError(
                "rollup canonical serialization is not one-pass: "
                f"expected 3000 serializations, got {serialization_count}"
            )
        if thousand["work"]["measurement_entries_examined"] != entries_per_document * 1000:
            raise ValueError("1000-attempt work accounting is not one-pass")
        if two_thousand["work"]["measurement_entries_examined"] != entries_per_document * 2000:
            raise ValueError("2000-attempt work accounting is not one-pass")
        if (
            two_thousand["work"]["measurement_entries_examined"]
            != 2 * thousand["work"]["measurement_entries_examined"]
        ):
            raise ValueError("rollup work does not scale linearly with attempt count")

        with tempfile.TemporaryDirectory() as temporary_directory:
            input_dir = Path(temporary_directory)
            (input_dir / "attempt.json").write_text(
                json.dumps(first, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output_path = input_dir / "rollup.json"
            command = [
                sys.executable,
                str(ROOT / "scripts" / "summarize_agent_evidence.py"),
                str(input_dir),
                "--output",
                str(output_path),
            ]
            first_run = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if first_run.returncode != 0:
                raise ValueError(
                    "first in-place rollup failed: "
                    + (first_run.stderr.strip() or first_run.stdout.strip())
                )
            first_output = output_path.read_text(encoding="utf-8")

            second_run = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if second_run.returncode != 0:
                raise ValueError(
                    "second in-place rollup failed: "
                    + (second_run.stderr.strip() or second_run.stdout.strip())
                )
            if output_path.read_text(encoding="utf-8") != first_output:
                raise ValueError("in-place rollup is not idempotent across repeated runs")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Agent rollup validation failed: {error}", file=sys.stderr)
        return 1

    print("Agent evidence rollup validation passed, including deterministic linear-work smoke.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
