#!/usr/bin/env python3

from __future__ import annotations

import sys

from validate_agent_landscape import main as validate_agent_landscape
from validate_rust_callgrind_adapter import main as validate_rust_callgrind
from validate_dhat_adapter import main as validate_dhat
from validate_application_counters import main as validate_application_counters
from validate_benchmarkdotnet_adapter import main as validate_benchmarkdotnet
from validate_input_snapshots import main as validate_input_snapshots
from validate_output_paths import main as validate_output_paths
from schema_validation import validator_for_schema


def main() -> int:
    agent = validate_agent_landscape()
    if agent != 0:
        return agent
    output_paths = validate_output_paths()
    if output_paths != 0:
        return output_paths
    validator_for_schema.cache_clear()
    callgrind = validate_rust_callgrind()
    if callgrind != 0:
        return callgrind
    dhat = validate_dhat()
    if dhat != 0:
        return dhat
    benchmarkdotnet = validate_benchmarkdotnet()
    if benchmarkdotnet != 0:
        return benchmarkdotnet
    application_counters = validate_application_counters()
    if application_counters != 0:
        return application_counters

    cache_info = validator_for_schema.cache_info()
    if cache_info.misses != 1 or cache_info.hits < 1:
        print(
            "Canonical schema validator cache regression: "
            f"expected one miss and at least one hit, got {cache_info}.",
            file=sys.stderr,
        )
        return 1

    input_snapshots = validate_input_snapshots()
    if input_snapshots != 0:
        return input_snapshots
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
