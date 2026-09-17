#!/usr/bin/env python3

from __future__ import annotations

from validate_agent_loop_adapter import main as validate_adapter
from validate_agent_rollup import main as validate_rollup


def main() -> int:
    adapter = validate_adapter()
    if adapter != 0:
        return adapter
    return validate_rollup()


if __name__ == "__main__":
    raise SystemExit(main())
