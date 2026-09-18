# Roadmap

Performance Evidence is the shared contract for deterministic computational-cost evidence across repositories. The roadmap intentionally separates measurement from visualization and architectural reasoning.

## Architectural boundaries

- **Performance Evidence owns the evidence contract.** Scenario identity, provenance, counters, comparison semantics, budget policy, measurement profiles, and adapter contracts live here.
- **Runtime Profiler consumes evidence.** Flamegraphs, interactive exploration, history, GitHub Pages, and rich presentation belong there.
- **Architecture review skills consume evidence.** They correlate code/dataflow changes with copies, allocations, materialization, repeated traversal, recomputation, and other work amplification.
- **Domain repositories own semantic counters.** A physics engine knows what a body visit or contact test means; a table package knows what row materialization means; React tooling knows what a render/commit means; the agent execution layer knows what an attempt and candidate mean.
- **Wall-clock time is an outcome, not the sole authority.** Deterministic or near-deterministic work evidence should be preferred for CI gating when possible; timing remains important calibration evidence.

## Evidence model

Every reproducible scenario should be able to emit a portable evidence record containing:

- schema version;
- scenario and workload identity;
- source revision and exact-head provenance;
- deterministic seed/configuration where applicable;
- environment/toolchain/profiler fingerprint;
- **useful work** counters: work that directly advances the scenario;
- **induced work** counters: traversals, allocations, allocated bytes, copies/bytes copied, materializations, recomputations, serialization, framework work, agent token use, etc.;
- outcome measurements such as elapsed time, throughput, frame time, time-to-green, or monetary cost;
- optional profiler artifacts and hashes;
- baseline provenance and comparison results.

The machine-readable artifact is authoritative. Markdown reports and GitHub Pages are derived views.

## Slice 1 — Canonical evidence contract

- [x] Define a versioned JSON Schema for `performance-evidence.json`.
- [x] Keep the base model language/framework neutral.
- [x] Represent counters as typed, unit-bearing measurements rather than a fixed list of profiler-specific fields.
- [x] Distinguish useful work, induced work, and outcomes explicitly.
- [x] Capture source SHA, workload identity/hash, seed, environment fingerprint, and artifact hashes.
- [x] Add valid and invalid fixtures.
- [x] Add deterministic validation in CI.
- [x] Document extension rules so domain counters remain comparable without centralizing domain semantics here.

## Integration slice — Agent run evidence profile

- [x] Define a machine-validated measurement-profile contract without creating a second evidence format.
- [x] Define `agent-run/v1` for one coding-agent implementation attempt.
- [x] Standardize candidate production, input/output/cached tokens, execution time, deterministic time-to-green, and monetary cost.
- [x] Map the profile to the existing `agent-loop-orchestrator` efficiency ledger while preserving orchestration/ledger ownership there.
- [x] Keep provider session identifiers out of portable artifacts.
- [x] Add a canonical valid fixture and include profiles in deterministic dogfood validation.
- [x] Teach `agent-loop-orchestrator` to export canonical per-attempt Performance Evidence using the profile.
- [x] Aggregate canonical attempt evidence in the weekly efficiency rollup without replacing the richer orchestrator ledger view.

## Slice 2 — Comparison and work amplification

- [x] Define exact-head vs baseline comparison semantics.
- [x] Add absolute and relative deltas without hiding zero/near-zero baselines.
- [x] Introduce first-class amplification ratios such as `entities_visited / entities_changed` and `bytes_copied / bytes_changed`.
- [x] Preserve raw measurements alongside derived ratios.
- [x] Define missing/incomparable evidence explicitly rather than silently coercing it.
- [x] Produce a stable machine-readable comparison artifact.

## Slice 3 — Budgets and CI policy

- [ ] Define deterministic work budgets independently from noisy wall-clock budgets.
- [ ] Support hard regression gates, informational thresholds, and calibration-only metrics.
- [ ] Require comparable scenario/workload provenance before applying a budget.
- [ ] Fail closed on malformed or mismatched authoritative evidence.
- [ ] Support non-retrying exact-head validation.
- [ ] Keep correctness tests separate from performance evidence and budgets.

## Slice 4 — Rust adapter

- [ ] Add an adapter path for deterministic instruction/cache/call evidence (for example Callgrind/iai-callgrind output).
- [ ] Add allocation evidence and copy profiling where available (for example DHAT-style evidence).
- [ ] Provide lightweight application counters for traversals, materializations, snapshots, recomputations, and bytes moved.
- [ ] Ensure instrumentation can be disabled without changing program semantics.
- [ ] Dogfood on a simulation/engine hot path that previously suffered from unnecessary copies/materialization.

## Slice 5 — .NET adapter

- [ ] Map BenchmarkDotNet allocation/GC diagnostics into the common evidence model.
- [ ] Support EventPipe/dotnet diagnostics as richer optional artifacts.
- [ ] Define a small semantic-counter bridge for domain work such as rows scanned/materialized and cache rebuilds.
- [ ] Keep reference-hardware counters separate from portable deterministic evidence when comparability is weak.

## Slice 6 — Browser and React adapter

- [ ] Integrate React render-budget evidence as framework work rather than a separate performance system.
- [ ] Capture interactions, commits, component renders, effects, DOM mutations, and relevant materialization counters.
- [ ] Support browser scenarios with deterministic inputs and trace/profiler artifacts.
- [ ] Track work amplification such as renders per semantic change or rows materialized per visible row.

## Slice 7 — WASM / boundary-cost evidence

- [ ] Measure work crossing Rust/WASM/JS boundaries.
- [ ] Record serialization/deserialization, copies, materializations, and uploaded bytes where observable.
- [ ] Detect repeated full-state transfer when delta transfer would preserve authority semantics.
- [ ] Keep Maps/rendering/simulation domain authority in their owning repositories.

## Slice 8 — Runtime Profiler integration

- [ ] Teach `runtime-profiler` to ingest canonical Performance Evidence artifacts.
- [ ] Show useful work and induced work next to timing outcomes.
- [ ] Visualize exact-head vs baseline deltas and amplification ratios.
- [ ] Link raw evidence to flamegraphs/traces/heap artifacts by hash.
- [ ] Publish historical evidence through the existing GitHub Pages approach without making Pages authoritative.

## Slice 9 — Architecture cost review skill

- [ ] Add a coding-agent skill that consumes a diff plus before/after evidence.
- [ ] Review ownership/dataflow for accidental snapshots, clones, boxing, eager collection, serialization, broad invalidation, repeated traversal, and recomputation.
- [ ] Correlate architectural findings with measured regressions rather than flagging patterns mechanically.
- [ ] Prefer findings such as “this boundary caused 2.7 MiB additional copying” over generic “avoid clone” advice.
- [ ] Require exact-head evidence when making integration decisions.

## Slice 10 — Portable evidence bundle

- [ ] Define a portable bundle containing Markdown summary, canonical JSON, profiler artifacts, hashes, and environment fingerprint.
- [ ] Make bundles reproducible enough for coding agents to inspect without rerunning the workload first.
- [ ] Preserve provenance from source SHA through generated reports.

## Slice 11 — Determinism and calibration

- [ ] Classify metrics by determinism/comparability level.
- [ ] Detect environment drift that invalidates comparison.
- [ ] Add repeated-browser/reference-hardware calibration without turning noisy measurements into brittle CI gates.
- [ ] Establish guidance for instruction counts, allocator evidence, hardware counters, browser traces, and wall-clock measurements.
- [ ] Detect instrumentation effects where feasible.

## Integration slice — CI artifact reuse economics

- [x] Define `ci-artifact-reuse/v1` for exact-head producer setup/build/upload cost and fan-out.
- [x] Keep artifact reuse recommendations advisory and separate from correctness/release authority.
- [x] Map reusable-workflows build-artifact receipts into portable useful-work, induced-work, and outcome measurements.
- [ ] Aggregate verified consumer materialization cost across downstream jobs.
- [ ] Calibrate rollout thresholds across cheap TypeScript builds and expensive Rust/WASM builds.

## Slice 12 — Adoption and convergence

Dogfood across deliberately different workloads before broad rollout:

1. simulation/physics: mutation/delta hot paths, contact search, snapshots;
2. data processing/tables: scans, indexes, materialization, collation;
3. React/browser: commits, renders, effects, DOM work;
4. rendering/WASM: uploads, boundary copies, frame work;
5. .NET services: allocations, query work, serialization, request-level semantic counters;
6. coding agents: tokens, attempts, execution time, time-to-green, escalation, and accepted candidates.

Then integrate the common contract into reusable workflows and repository convergence so new projects inherit evidence collection early rather than adding profiling only after performance degrades.

## Guiding review questions

For each hot path or performance-sensitive PR, the eventual tooling should make these questions answerable:

- What is the useful work of this scenario?
- What induced work does the implementation perform to achieve it?
- Which work scales with input size, changed state, visible state, interaction count, or agent attempt count?
- Did a delta become a snapshot?
- Did a view/borrow become an owned copy?
- Did laziness become eager materialization?
- Did one traversal become several?
- Did unchanged data cross an FFI/WASM/network boundary again?
- Was derived state recomputed despite unchanged authority?
- Did a routing/escalation choice consume more tokens or time for an equivalent task without improving checked output?
- Which changes are deterministic regressions, and which are only noisy timing differences?
