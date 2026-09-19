# Rust Callgrind adapter

The `rust-callgrind/v1` adapter enriches an existing canonical Performance Evidence document with deterministic Callgrind work counters. It is deliberately an offline adapter rather than a benchmark framework.

The base evidence document remains authoritative for:

- scenario and workload identity;
- source revision and dirty state;
- domain-owned useful-work counters;
- domain-owned induced-work counters such as body visits, materializations, or bytes moved;
- outcome measurements.

The adapter preserves those fields, adds profiler-derived induced work, hashes the raw Callgrind artifact, and derives a new environment fingerprint from the base environment plus the adapter and Callgrind event/tool identity.

## Mapped events

The first adapter contract maps common Callgrind summary events:

| Callgrind | Performance Evidence |
| --- | --- |
| `Ir` | `cpu.instructions` |
| `Dr` | `memory.data_reads` |
| `Dw` | `memory.data_writes` |
| `I1mr` | `cache.l1_instruction_read_misses` |
| `D1mr` | `cache.l1_data_read_misses` |
| `D1mw` | `cache.l1_data_write_misses` |
| `ILmr` | `cache.last_level_instruction_read_misses` |
| `DLmr` | `cache.last_level_data_read_misses` |
| `DLmw` | `cache.last_level_data_write_misses` |

The adapter also sums explicit Callgrind `calls=` directives into `cpu.calls`. Unknown events are preserved in the `rust.callgrind` extension as `unmapped_events`; they are not silently reinterpreted.

Missing `events` or `summary` data, summary/event arity mismatches, duplicate event declarations, and measurement-name collisions fail closed.

## Usage

```sh
python scripts/convert_rust_callgrind.py \
  base-performance-evidence.json \
  callgrind.out \
  --output performance-evidence.callgrind.json
```

The default artifact path is the Callgrind input filename. Use `--artifact-path` when a repository needs a stable portable bundle path.

This adapter does not decide what useful work means and does not invoke Valgrind itself. Repositories or reusable execution layers own scenario execution; Performance Evidence owns only the portable mapping and resulting evidence semantics.
