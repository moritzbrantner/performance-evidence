#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from merge_application_counters import load_json_object, merge
from schema_validation import validation_errors


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "application-counters"
SCHEMA_PATH = ROOT / "schema" / "performance-evidence.schema.json"


def expect_value_error(action, fragment: str) -> None:
    try:
        action()
    except ValueError as error:
        if fragment not in str(error):
            raise
    else:
        raise ValueError(f"expected ValueError containing {fragment!r}")


def measurement_map(document: dict) -> dict[str, dict]:
    return {
        entry["name"]: entry
        for group in ("useful_work", "induced_work", "outcomes")
        for entry in document["measurements"][group]
    }


def main() -> int:
    try:
        base = load_json_object(FIXTURE_DIR / "base-evidence.json")
        counter_path = FIXTURE_DIR / "counters.json"
        fragment_bytes = counter_path.read_bytes()
        fragment = load_json_object(counter_path)

        merged = merge(
            base,
            fragment,
            fragment_bytes,
            "semantic-counters.json",
        )

        if merged["scenario"] != base["scenario"]:
            raise ValueError("counter bridge changed scenario/workload authority")
        if merged["source"] != base["source"]:
            raise ValueError("counter bridge changed source authority")
        if merged["environment"] != base["environment"]:
            raise ValueError("counter bridge changed environment authority")
        if merged["measurements"]["outcomes"] != base["measurements"]["outcomes"]:
            raise ValueError("counter bridge changed existing outcomes")

        expected = {
            "simulation.state_changes": (3, "count", "counter"),
            "simulation.entity_visits": (120, "count", "counter"),
            "data.materializations": (4, "count", "counter"),
            "state.snapshots": (1, "count", "counter"),
            "state.recomputations": (2, "count", "counter"),
            "memory.bytes_moved": (8192, "byte", "size"),
        }
        mapped = measurement_map(merged)
        for name, (value, unit, measurement_type) in expected.items():
            if mapped.get(name) != {
                "name": name,
                "value": value,
                "unit": unit,
                "measurement_type": measurement_type,
            }:
                raise ValueError(f"unexpected semantic counter {name}: {mapped.get(name)!r}")

        if merged["extensions"]["application.counters"] != {
            "adapter_contract": "application-counters/v1",
            "counter_count": 6,
            "groups": ["useful_work", "induced_work"],
        }:
            raise ValueError("counter bridge emitted unexpected provenance extension")
        artifact = merged["artifacts"][-1]
        if artifact["kind"] != "application-counters":
            raise ValueError("counter bridge did not preserve raw fragment as an artifact")
        if artifact["path"] != "semantic-counters.json":
            raise ValueError("counter bridge did not preserve portable artifact path")

        schema = load_json_object(SCHEMA_PATH)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = validation_errors(validator, merged)
        if errors:
            raise ValueError(
                "merged counter evidence violates canonical contract:\n  - "
                + "\n  - ".join(errors)
            )

        disabled_path = FIXTURE_DIR / "disabled.json"
        disabled = merge(
            base,
            load_json_object(disabled_path),
            disabled_path.read_bytes(),
            "disabled.json",
        )
        if disabled != base:
            raise ValueError("disabled application counters were not a strict no-op")

        collision_fragment = {
            "outcomes": [
                {
                    "name": "time.elapsed",
                    "value": 1,
                    "unit": "ns",
                    "measurement_type": "duration",
                }
            ]
        }
        expect_value_error(
            lambda: merge(
                base,
                collision_fragment,
                json.dumps(collision_fragment).encode("utf-8"),
                "collision.json",
            ),
            "collide",
        )

        duplicate_fragment = {
            "useful_work": [
                {
                    "name": "simulation.duplicate",
                    "value": 1,
                    "unit": "count",
                    "measurement_type": "counter",
                }
            ],
            "induced_work": [
                {
                    "name": "simulation.duplicate",
                    "value": 2,
                    "unit": "count",
                    "measurement_type": "counter",
                }
            ],
        }
        expect_value_error(
            lambda: merge(
                base,
                duplicate_fragment,
                json.dumps(duplicate_fragment).encode("utf-8"),
                "duplicate.json",
            ),
            "duplicates",
        )

        invalid_fragment = {
            "induced_work": [
                {
                    "name": "simulation.invalid",
                    "value": -1,
                    "unit": "count",
                    "measurement_type": "counter",
                }
            ]
        }
        expect_value_error(
            lambda: merge(
                base,
                invalid_fragment,
                json.dumps(invalid_fragment).encode("utf-8"),
                "invalid.json",
            ),
            "invalid",
        )

        unknown_field = {"counters": []}
        expect_value_error(
            lambda: merge(
                base,
                unknown_field,
                json.dumps(unknown_field).encode("utf-8"),
                "unknown.json",
            ),
            "unsupported fields",
        )

        portable = "profiles/portable.json"
        override = merge(
            base,
            fragment,
            fragment_bytes,
            portable,
        )
        if override["artifacts"][-1]["path"] != portable:
            raise ValueError("counter bridge artifact-path override was not preserved")

        expect_value_error(
            lambda: merge(
                base,
                fragment,
                fragment_bytes,
                "/tmp/non-portable.json",
            ),
            "portable relative POSIX path",
        )

        extension_collision = copy.deepcopy(base)
        extension_collision["extensions"] = {
            "application.counters": {"owner": "repository"}
        }
        expect_value_error(
            lambda: merge(
                extension_collision,
                fragment,
                fragment_bytes,
                "semantic-counters.json",
            ),
            "already defines application.counters",
        )

    except (OSError, ValueError, json.JSONDecodeError) as error:
        import sys

        print(f"Application counter bridge validation failed: {error}", file=sys.stderr)
        return 1

    print("Application counter bridge validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
