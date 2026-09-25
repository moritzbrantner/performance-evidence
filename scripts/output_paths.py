#!/usr/bin/env python3

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def validate_output_path(output: Path, inputs: tuple[Path, ...]) -> None:
    """Reject outputs that would replace or alias any declared input path."""
    resolved_output = output.resolve()
    output_exists = output.exists()

    for input_path in inputs:
        aliases_input = resolved_output == input_path.resolve()
        if not aliases_input and output_exists and input_path.exists():
            aliases_input = output.samefile(input_path)

        if aliases_input:
            raise ValueError(
                f"output path must not overwrite input artifact {input_path}"
            )



def write_text_atomic(output: Path, contents: str) -> None:
    """Replace a machine-managed text artifact only after the full write succeeds."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temporary_path, output)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
