#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from output_paths import validate_output_path


ROOT = Path(__file__).resolve().parents[1]


def expect_rejected(command: list[str], protected_path: Path) -> None:
    original = protected_path.read_bytes()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 1:
        raise ValueError(
            f"destructive output/input collision unexpectedly returned {result.returncode}: "
            f"{' '.join(command)}"
        )
    if "output path must not overwrite input artifact" not in result.stderr:
        raise ValueError(
            "destructive output/input collision failed for an unexpected reason: "
            + result.stderr.strip()
        )
    if protected_path.read_bytes() != original:
        raise ValueError(
            f"rejected destructive command modified protected input {protected_path}"
        )


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)

            dhat = temporary / "dhat.json"
            shutil.copyfile(ROOT / "fixtures" / "dhat" / "heap.json", dhat)
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "convert_dhat.py"),
                    str(ROOT / "fixtures" / "rust-callgrind" / "base-evidence.json"),
                    str(dhat),
                    "--output",
                    str(dhat),
                ],
                dhat,
            )

            callgrind = temporary / "callgrind.out"
            shutil.copyfile(
                ROOT / "fixtures" / "rust-callgrind" / "callgrind.out",
                callgrind,
            )
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "convert_rust_callgrind.py"),
                    str(ROOT / "fixtures" / "rust-callgrind" / "base-evidence.json"),
                    str(callgrind),
                    "--output",
                    str(callgrind),
                ],
                callgrind,
            )

            counters = temporary / "counters.json"
            shutil.copyfile(
                ROOT / "fixtures" / "application-counters" / "counters.json",
                counters,
            )
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "merge_application_counters.py"),
                    str(ROOT / "fixtures" / "application-counters" / "base-evidence.json"),
                    str(counters),
                    "--output",
                    str(counters),
                ],
                counters,
            )

            benchmark = temporary / "benchmarkdotnet.json"
            shutil.copyfile(
                ROOT / "fixtures" / "benchmarkdotnet" / "benchmarkdotnet.json",
                benchmark,
            )
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "convert_benchmarkdotnet.py"),
                    str(ROOT / "fixtures" / "benchmarkdotnet" / "base-evidence.json"),
                    str(benchmark),
                    "--benchmark",
                    "Example.TableBenchmarks.Materialize",
                    "--output",
                    str(benchmark),
                ],
                benchmark,
            )

            baseline = temporary / "baseline.json"
            shutil.copyfile(
                ROOT / "fixtures" / "comparison" / "baseline.json",
                baseline,
            )
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "compare_evidence.py"),
                    str(baseline),
                    str(ROOT / "fixtures" / "comparison" / "candidate.json"),
                    "--output",
                    str(baseline),
                ],
                baseline,
            )

            policy = temporary / "policy.json"
            shutil.copyfile(
                ROOT / "fixtures" / "budget" / "policy-pass.json",
                policy,
            )
            expect_rejected(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "evaluate_budget.py"),
                    str(policy),
                    str(ROOT / "fixtures" / "comparison" / "expected.json"),
                    "--output",
                    str(policy),
                ],
                policy,
            )

            hardlink_source = temporary / "hardlink-source.json"
            hardlink_source.write_text('{"source": true}\n', encoding="utf-8")
            hardlink_output = temporary / "hardlink-output.json"
            os.link(hardlink_source, hardlink_output)
            try:
                validate_output_path(hardlink_output, (hardlink_source,))
            except ValueError:
                pass
            else:
                raise ValueError("hard-link output alias was not rejected")
    except (OSError, ValueError) as error:
        print(f"Output-path validation failed: {error}", file=sys.stderr)
        return 1

    print("Transformation output-path validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
