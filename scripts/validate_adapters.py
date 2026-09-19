#!/usr/bin/env python3

from __future__ import annotations

from validate_agent_landscape import main as validate_agent_landscape
from validate_rust_callgrind_adapter import main as validate_rust_callgrind
from validate_dhat_adapter import main as validate_dhat
from validate_application_counters import main as validate_application_counters


def main() -> int:
    agent = validate_agent_landscape()
    if agent != 0:
        return agent
    callgrind = validate_rust_callgrind()
    if callgrind != 0:
        return callgrind
    dhat = validate_dhat()
    if dhat != 0:
        return dhat
    return validate_application_counters()


if __name__ == "__main__":
    raise SystemExit(main())
