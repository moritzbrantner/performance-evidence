#!/usr/bin/env python3

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    contents: bytes
    sha256: str


def read_input_snapshot(path: Path) -> InputSnapshot:
    contents = path.read_bytes()
    return InputSnapshot(
        contents=contents,
        sha256="sha256:" + hashlib.sha256(contents).hexdigest(),
    )
