#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_ADOPTED = {"environment", "tooling", "conventions", "renovate"}
KNOWN_COMPONENT_GAP = "foundation-components-unsupported"
TRACKING_ISSUE = "moritzbrantner/coding-tooling#233"


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError("foundation report must be a JSON object")
    return report


def verify(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    data = report.get("data")
    if not isinstance(data, dict):
        return ["foundation report is missing object data"]

    components = data.get("components")
    if not isinstance(components, dict):
        return ["foundation report is missing component evidence"]

    for name in sorted(REQUIRED_ADOPTED):
        component = components.get(name)
        if not isinstance(component, dict):
            errors.append(f"foundation component {name!r} is missing")
            continue
        status = component.get("status")
        if status != "adopted":
            errors.append(
                f"foundation component {name!r} must be adopted, got {status!r}"
            )

    commands = components.get("commands")
    if not isinstance(commands, dict):
        errors.append("foundation component 'commands' is missing")
    else:
        status = commands.get("status")
        diagnostics = commands.get("diagnostics", [])
        codes = {
            diagnostic.get("code")
            for diagnostic in diagnostics
            if isinstance(diagnostic, dict)
        }
        if status == "adopted":
            pass
        elif status == "unsupported" and codes == {KNOWN_COMPONENT_GAP}:
            print(
                "Repository-level command discovery is the known "
                f"{TRACKING_ISSUE} gap; preserving it as upstream evidence."
            )
        else:
            errors.append(
                "foundation component 'commands' must be adopted or the exact "
                f"tracked {KNOWN_COMPONENT_GAP!r} gap, got status={status!r}, "
                f"diagnostics={sorted(code for code in codes if code)}"
            )

    summary = data.get("summary")
    if not isinstance(summary, dict):
        errors.append("foundation report is missing summary")
    else:
        if summary.get("missing") != 0:
            errors.append(
                f"foundation summary has missing={summary.get('missing')!r}; expected 0"
            )
        if summary.get("invalid") != 0:
            errors.append(
                f"foundation summary has invalid={summary.get('invalid')!r}; expected 0"
            )
        unsupported = summary.get("unsupported")
        if unsupported not in {0, 1}:
            errors.append(
                f"foundation summary has unsupported={unsupported!r}; expected 0 or 1"
            )

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} FOUNDATION_REPORT.json", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    try:
        errors = verify(load_report(path))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Foundation verification failed: {error}", file=sys.stderr)
        return 1

    if errors:
        print("Foundation verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Repository-owned foundation state is adopted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
