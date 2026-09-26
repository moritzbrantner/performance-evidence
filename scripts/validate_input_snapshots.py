#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import compare_evidence
import convert_dhat
import evaluate_budget
from validate_schema import load_json_bytes


ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(contents: bytes) -> str:
    return "sha256:" + hashlib.sha256(contents).hexdigest()


def validate_utf8_only_snapshots() -> None:
    source_text = (ROOT / "fixtures" / "dhat" / "heap.json").read_text(
        encoding="utf-8"
    )
    for encoding in ("utf-16", "utf-32"):
        encoded = source_text.encode(encoding)
        for label, parser in (
            ("shared JSON snapshot", load_json_bytes),
            ("DHAT snapshot", convert_dhat.parse_dhat),
        ):
            try:
                parser(encoded)
            except UnicodeDecodeError:
                continue
            raise ValueError(f"{label} unexpectedly accepted {encoding} input")


def validate_dhat_snapshot(temporary: Path) -> None:
    source = ROOT / "fixtures" / "dhat" / "heap.json"
    mutable = temporary / "mutable-dhat.json"
    original_bytes = source.read_bytes()
    mutable.write_bytes(original_bytes)
    expected_hash = sha256_bytes(original_bytes)

    base = convert_dhat.load_json_object(
        ROOT / "fixtures" / "rust-callgrind" / "base-evidence.json"
    )
    original_parse = convert_dhat.parse_dhat

    def parse_then_mutate(source_value):
        parsed = original_parse(source_value)
        mutable.write_bytes(original_bytes + b" ")
        return parsed

    convert_dhat.parse_dhat = parse_then_mutate
    try:
        converted = convert_dhat.convert(base, mutable)
    finally:
        convert_dhat.parse_dhat = original_parse

    artifact = converted["artifacts"][-1]
    if artifact["sha256"] != expected_hash:
        raise ValueError(
            "DHAT artifact hash was not bound to the bytes used for parsing"
        )
    if mutable.read_bytes() == original_bytes:
        raise ValueError("DHAT provenance regression did not mutate the source fixture")


def validate_comparison_snapshot(temporary: Path) -> None:
    baseline_source = ROOT / "fixtures" / "comparison" / "baseline.json"
    baseline = temporary / "baseline.json"
    original_bytes = baseline_source.read_bytes()
    baseline.write_bytes(original_bytes)
    expected_hash = sha256_bytes(original_bytes)

    original_validation_errors = compare_evidence.validation_errors
    mutation_done = False

    def validate_then_mutate(validator, document):
        nonlocal mutation_done
        errors = original_validation_errors(validator, document)
        if not mutation_done:
            baseline.write_bytes(original_bytes + b" ")
            mutation_done = True
        return errors

    compare_evidence.validation_errors = validate_then_mutate
    try:
        comparison = compare_evidence.compare_documents(
            baseline,
            ROOT / "fixtures" / "comparison" / "candidate.json",
            "1111111111111111111111111111111111111111",
            [
                (
                    "physics.body_visits_per_changed_body",
                    "physics.body_visits",
                    "physics.changed_bodies",
                )
            ],
        )
    finally:
        compare_evidence.validation_errors = original_validation_errors

    if comparison["baseline"]["evidence_hash"] != expected_hash:
        raise ValueError(
            "comparison baseline hash was not bound to the validated baseline bytes"
        )
    if baseline.read_bytes() == original_bytes:
        raise ValueError(
            "comparison provenance regression did not mutate the baseline fixture"
        )


def validate_budget_snapshot(temporary: Path) -> None:
    policy_source = ROOT / "fixtures" / "budget" / "policy-pass.json"
    policy = temporary / "policy.json"
    original_bytes = policy_source.read_bytes()
    policy.write_bytes(original_bytes)
    expected_hash = sha256_bytes(original_bytes)

    original_validate_policy_semantics = evaluate_budget.validate_policy_semantics

    def validate_then_mutate(document):
        original_validate_policy_semantics(document)
        policy.write_bytes(original_bytes + b" ")

    evaluate_budget.validate_policy_semantics = validate_then_mutate
    try:
        evaluation = evaluate_budget.evaluate_budget(
            policy,
            ROOT / "fixtures" / "comparison" / "expected.json",
        )
    finally:
        evaluate_budget.validate_policy_semantics = original_validate_policy_semantics

    if evaluation["policy"]["sha256"] != expected_hash:
        raise ValueError(
            "budget policy hash was not bound to the validated policy bytes"
        )
    if policy.read_bytes() == original_bytes:
        raise ValueError("budget provenance regression did not mutate the policy fixture")


def main() -> int:
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            validate_utf8_only_snapshots()
            validate_dhat_snapshot(temporary)
            validate_comparison_snapshot(temporary)
            validate_budget_snapshot(temporary)
    except (OSError, ValueError) as error:
        print(f"Input snapshot validation failed: {error}", file=sys.stderr)
        return 1

    print("Immutable input snapshot validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
