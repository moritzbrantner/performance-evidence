# DHAT allocation and copy adapter

The `dhat/v1` adapter enriches canonical Performance Evidence with deterministic allocation or copy-profile summaries from DHAT file-format version 2.

The adapter accepts Valgrind DHAT heap/copy output and Rust `dhat` crate heap output. It does not run the profiler and does not reinterpret repository-owned useful work.

## Heap mode

For `heap` and `rust-heap`, the adapter always reports:

- `memory.allocated_bytes` from the sum of program-point `tb`;
- `memory.allocations` from the sum of `tbk`.

When every program point provides the corresponding field it also reports:

- `memory.bytes_at_global_peak` / `memory.blocks_at_global_peak` from `gb` / `gbk`;
- `memory.bytes_at_end` / `memory.blocks_at_end` from `eb` / `ebk`;
- `memory.heap_read_bytes` / `memory.heap_written_bytes` from `rb` / `wb`.

Missing optional fields remain missing. In particular, Rust's `dhat` crate does not track heap read/write accesses, so the adapter does not manufacture zero read/write counts.

Per-program-point maxima and lifetime totals are intentionally not aggregated in this first adapter contract because they do not compose into an unambiguous global metric.

## Copy mode

For `copy`, the adapter reports:

- `memory.bytes_copied` from total `tb`;
- `memory.copy_operations` from total `tbk`.

This makes DHAT copy profiling directly usable for snapshot/materialization/copy-amplification evidence.

## Provenance

The original scenario, workload, source revision, dirty state, and domain counters are preserved. The raw DHAT JSON is linked as a hashed artifact. A derived environment fingerprint includes the base environment fingerprint plus DHAT file version, mode, and time unit so incompatible profiler modes do not compare accidentally.

## Usage

```sh
python scripts/convert_dhat.py \
  base-performance-evidence.json \
  dhat.json \
  --output performance-evidence.dhat.json
```

Malformed file versions/modes, invalid program-point counters, measurement collisions, and duplicate DHAT artifact/extension ownership fail closed.
