# Performance Evidence contract

`schema/performance-evidence.schema.json` is the canonical interchange contract for one performance scenario execution.

## Classification

Measurements are deliberately separated into three groups:

- `useful_work`: semantic work that directly advances the scenario, such as changed entities, produced contacts, or consumed rows;
- `induced_work`: implementation work needed to produce the result, such as visits, allocations, copies, materializations, instructions, renders, or serialization;
- `outcomes`: externally observed results such as elapsed time, throughput, or frame time.

The distinction lets consumers compute work amplification without pretending that elapsed time explains why a regression happened.

## Measurement identity

A measurement consists of:

- a stable `name`;
- a numeric, non-negative `value`;
- an explicit `unit`;
- a `measurement_type` describing how the value behaves.

Measurement names are unique across the entire evidence document. This prevents one artifact from classifying the same metric as both useful and induced work, or from relying on array position to distinguish duplicate samples.

Domain-specific counters should use a stable namespace, for example:

- `physics.body_visits`;
- `memory.bytes_copied`;
- `table.rows_materialized`;
- `react.component_renders`;
- `wasm.bytes_transferred`.

Performance Evidence does not centrally define every domain metric. The repository that owns a domain owns the semantics of its counters; this contract only makes those counters portable.

## Provenance

Evidence is not comparable without workload and source provenance. Every document therefore carries:

- a scenario identifier;
- a workload identifier and SHA-256 fingerprint;
- the exact source revision and whether the working tree was dirty;
- an environment fingerprint;
- optional platform, toolchain, and collector metadata.

A later comparison policy may reject dirty or environment-mismatched evidence even though the base interchange schema can represent it.

## Artifacts

Profiler outputs are optional attachments referenced by kind, path, and SHA-256 hash. They are supporting evidence, not the canonical performance record. This keeps the core artifact usable even when a particular profiler is unavailable.

## Extensions

Top-level extensions must live inside `extensions` and use a namespaced key such as `example.physics` or `runtime-profiler.trace`. Extensions must not shadow or reinterpret canonical fields.

Prefer adding a normal measurement instead of an extension when the information can be represented as a named numeric value with a unit. Extensions are for structured metadata that does not fit the measurement model.

A consumer must be able to ignore unknown extensions without changing the meaning of canonical fields.

## Validation

Install the pinned validation dependency and run:

```sh
python -m pip install -r requirements-dev.txt
python scripts/validate_schema.py
```

Validation checks the Draft 2020-12 schema, all positive/negative fixtures, and semantic invariants that are intentionally clearer outside JSON Schema.

The machine-readable JSON is authoritative. Markdown summaries, GitHub Pages, flamegraphs, and runtime-profiler views are derived representations.
