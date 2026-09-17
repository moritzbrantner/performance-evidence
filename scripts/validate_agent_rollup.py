#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

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


def main() -> int:
    try:
        first = load_fixture()
        second = copy.deepcopy(first)
        second_extension = second["extensions"]["agent.execution"]
        second_extension["run_id"] = "018f5d43-4d1c-7fd5-aed5-d451fd71c111"
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

        # Deterministic cost smoke: work accounting must scale exactly with input size.
        # This avoids a brittle wall-clock CI budget while catching accidental rescans.
        entries_per_document = sum(
            len(first["measurements"][group])
            for group in ("useful_work", "induced_work", "outcomes")
        )
        thousand = summarize_documents([first] * 1000)
        two_thousand = summarize_documents([first] * 2000)
        if thousand["work"]["measurement_entries_examined"] != entries_per_document * 1000:
            raise ValueError("1000-attempt work accounting is not one-pass")
        if two_thousand["work"]["measurement_entries_examined"] != entries_per_document * 2000:
            raise ValueError("2000-attempt work accounting is not one-pass")
        if (
            two_thousand["work"]["measurement_entries_examined"]
            != 2 * thousand["work"]["measurement_entries_examined"]
        ):
            raise ValueError("rollup work does not scale linearly with attempt count")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Agent rollup validation failed: {error}", file=sys.stderr)
        return 1

    print("Agent evidence rollup validation passed, including deterministic linear-work smoke.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
