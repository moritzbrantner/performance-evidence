#!/usr/bin/env python3

from __future__ import annotations

from validate_agent_landscape import main as validate_agent_landscape
from validate_rust_callgrind_adapter import main as validate_rust_callgrind


def main() -> int:
    agent = validate_agent_landscape()
    if agent != 0:
        return agent
    return validate_rust_callgrind()


if __name__ == "__main__":
    raise SystemExit(main())
