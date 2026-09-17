# AGENTS.md

## Purpose

`performance-evidence` owns the portable, language- and profiler-neutral contract for computational-cost evidence. Keep useful work, induced work, outcomes, provenance, comparison semantics, and CI policy here. Do not move visualization or profiler-specific exploration into this repository.

## Authority boundaries

- The canonical machine-readable evidence contract is authoritative; Markdown and Pages are derived views.
- Domain repositories own the semantics of their counters. This repository defines how counters are represented and compared, not what a physics contact or React render means.
- `runtime-profiler` consumes evidence for exploration and presentation; it does not own the evidence contract.
- `coding-tooling` owns deterministic repository discovery, conformance, findings, and validation orchestration. Do not duplicate those mechanics here.
- Architecture-review skills consume evidence and correlate measured regressions with code/dataflow changes; heuristic findings are advisory unless independently established as defects.

## Deterministic work

- Prefer work counters and reproducible provenance over wall-clock timing for authoritative CI decisions.
- Keep correctness validation separate from performance budgets.
- Any generated evidence must identify the exact source revision and environment fingerprint used to produce it.
- Scripts must be deterministic and idempotent for identical repository state and declared inputs.
- Do not accept or hide missing/incomparable evidence by coercing it into zero.

## Validation

`.coding-tooling.json` is the repository validation contract. Use its declared capability commands instead of inventing alternate validation paths.

For focused contract work, `python scripts/validate_schema.py` remains the narrow check. Repository-wide validation is the `fast` tier through `coding-tooling`, with conformance and deterministic findings checked separately in hosted CI.

The repository dogfoods its own evidence contract: validation can emit a canonical evidence artifact describing the deterministic work performed by the contract-validation scenario. That artifact is CI evidence, not a committed historical baseline.

## Convergence

Apply the repository-convergence discipline one material seam at a time: establish exact-head evidence, select the strongest reproducible finding, make the narrowest coherent repair, validate progressively, re-observe once, and report whether the material workset decreased. Do not treat cosmetic or heuristic findings as blockers without repository policy or independent evidence.
