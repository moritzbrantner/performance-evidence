#!/usr/bin/env python3

from __future__ import annotations

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
