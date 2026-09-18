# Performance Evidence

A language- and profiler-neutral foundation for making computational work observable, comparable, and reviewable.

Performance Evidence treats elapsed time as an outcome rather than the whole explanation. Its primary job is to capture deterministic or near-deterministic evidence about the work a program performs: traversals, allocations, copies, materializations, recomputation, framework work, agent token use, and other domain-specific counters.

## Responsibilities

This repository owns:

- the canonical performance-evidence interchange contract;
- scenario identity, workload provenance, seeds, source revisions, and environment fingerprints;
- useful-work and induced-work counters;
- exact-head/baseline comparison semantics;
- portable validation and CI policy primitives;
- adapters and measurement profiles that translate profiler/framework/agent output into the canonical evidence model.

It does **not** own rich profiling UI, historical exploration, or agent orchestration. `runtime-profiler` should consume these artifacts for analysis and presentation. Coding-agent architecture review skills should consume the same artifacts when reasoning about copies, allocations, materialization, recomputation, work amplification, and execution cost.

## Core principle

> Make useful work and induced work observable separately.

A useful performance review should be able to answer not only “did this get slower?” but also “what additional work did this change cause?”

Examples include:

- entities visited / entities changed;
- bytes copied / bytes changed;
- rows materialized / rows consumed;
- component renders / semantic UI changes;
- contacts tested / contacts produced;
- snapshots produced / explicitly requested snapshots;
- agent tokens consumed / accepted candidate produced.

## Contract

The first implementation slice establishes the versioned JSON contract in [`schema/performance-evidence.schema.json`](schema/performance-evidence.schema.json). Measurement profiles are separately validated by [`schema/measurement-profile.schema.json`](schema/measurement-profile.schema.json). Exact-head/baseline comparisons use [`schema/performance-comparison.schema.json`](schema/performance-comparison.schema.json) and preserve the original evidence artifacts as the measurement authority. See [`docs/contract.md`](docs/contract.md) and [`docs/comparison.md`](docs/comparison.md).

Validate it locally with:

```sh
python -m pip install -r requirements-dev.txt
python scripts/validate_schema.py
```

## Agent landscape

Performance Evidence remains the canonical computational-cost payload when used by coding agents. Repository capability discovery belongs to `coding-tooling`, hosted execution to `reusable-workflows`, profiling/exploration to `runtime-profiler`, and durable orchestration to `agent-loop-orchestrator`. When evidence crosses an independently owned component boundary, `agent-contracts` may wrap the immutable artifact as an `agent.evidence/v1` reference rather than replacing this schema.

The initial [`agent-run/v1`](profiles/agent-run-v1.json) profile standardizes one implementation attempt: candidate production, token use, execution time, deterministic time-to-green, and cost. It maps directly from the existing `agent-loop-orchestrator` efficiency ledger without moving ledger or routing authority into this repository. See [`docs/agent-run-profile.md`](docs/agent-run-profile.md).

An existing `agent-loop-efficiency` report can be converted deterministically into one canonical artifact per attempt:

```sh
python scripts/convert_agent_loop_efficiency.py \
  agent-loop-efficiency.json \
  .artifacts/performance-evidence/agent-runs \
  --source-dirty false
```

Pass `--source-dirty false` only when the execution layer established an exact clean baseline. The adapter preserves missing token/time/cost telemetry as missing instead of converting it to zero.

See [`docs/agent-landscape.md`](docs/agent-landscape.md) for the direct repository path, cross-component path, and integration invariants.

CI artifact producers can use the [`ci-artifact-reuse/v1` profile](docs/ci-artifact-reuse-profile.md) to report setup, build, upload, artifact-size, and fan-out economics without turning those measurements into correctness or release authority.

See [ROADMAP.md](ROADMAP.md) for the planned slices.
