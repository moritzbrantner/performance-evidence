# Performance Evidence

A language- and profiler-neutral foundation for making computational work observable, comparable, and reviewable.

Performance Evidence treats elapsed time as an outcome rather than the whole explanation. Its primary job is to capture deterministic or near-deterministic evidence about the work a program performs: traversals, allocations, copies, materializations, recomputation, framework work, and other domain-specific counters.

## Responsibilities

This repository owns:

- the canonical performance-evidence interchange contract;
- scenario identity, workload provenance, seeds, source revisions, and environment fingerprints;
- useful-work and induced-work counters;
- exact-head/baseline comparison semantics;
- portable validation and CI policy primitives;
- adapters that translate profiler/framework output into the canonical evidence model.

It does **not** own rich profiling UI or historical exploration. `runtime-profiler` should consume these artifacts for analysis and presentation. Coding-agent architecture review skills should consume the same artifacts when reasoning about copies, allocations, materialization, recomputation, and work amplification.

## Core principle

> Make useful work and induced work observable separately.

A useful performance review should be able to answer not only “did this get slower?” but also “what additional work did this change cause?”

Examples include:

- entities visited / entities changed;
- bytes copied / bytes changed;
- rows materialized / rows consumed;
- component renders / semantic UI changes;
- contacts tested / contacts produced;
- snapshots produced / explicitly requested snapshots.

## Contract

The first implementation slice establishes the versioned JSON contract in [`schema/performance-evidence.schema.json`](schema/performance-evidence.schema.json). See [`docs/contract.md`](docs/contract.md) for classification, provenance, measurement identity, artifact, and extension rules.

Validate it locally with:

```sh
python -m pip install -r requirements-dev.txt
python scripts/validate_schema.py
```

## Agent landscape

Performance Evidence remains the canonical computational-cost payload when used by coding agents. Repository capability discovery belongs to `coding-tooling`, hosted execution to `reusable-workflows`, profiling/exploration to `runtime-profiler`, and durable orchestration to `agent-loop-orchestrator`. When evidence crosses an independently owned component boundary, `agent-contracts` may wrap the immutable artifact as an `agent.evidence/v1` reference rather than replacing this schema.

See [`docs/agent-landscape.md`](docs/agent-landscape.md) for the direct repository path, cross-component path, and integration invariants.

See [ROADMAP.md](ROADMAP.md) for the planned slices.
