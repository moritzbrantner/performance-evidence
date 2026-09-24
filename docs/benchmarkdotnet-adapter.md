# BenchmarkDotNet memory adapter

The `benchmarkdotnet-memory/v1` adapter maps BenchmarkDotNet JSON exporter memory diagnostics into canonical Performance Evidence without requiring a .NET runtime in this repository.

## Input boundary

The adapter consumes:

1. an existing canonical Performance Evidence document whose scenario, workload, source revision, and domain counters remain authoritative; and
2. a BenchmarkDotNet JSON exporter artifact.

When the JSON contains more than one benchmark, callers must select one exact `FullName` or `DisplayInfo` with `--benchmark`. This avoids combining measurements from different benchmark cases or choosing one heuristically.

## Canonical measurements

For the selected benchmark, the `Memory` object maps to induced work:

| BenchmarkDotNet JSON | Performance Evidence | Unit | Type |
| --- | --- | --- | --- |
| `TotalOperations` | `dotnet.benchmark_operations` | `operation` | counter |
| `Gen0Collections` | `dotnet.gc.gen0_collections` | `count` | counter |
| `Gen1Collections` | `dotnet.gc.gen1_collections` | `count` | counter |
| `Gen2Collections` | `dotnet.gc.gen2_collections` | `count` | counter |
| `BytesAllocatedPerOperation` | `memory.allocated_bytes_per_operation` | `byte/operation` | size |

The JSON exporter fields above are the raw GC statistics. BenchmarkDotNet's human-readable MemoryDiagnoser table commonly presents generation counts normalized per 1,000 operations; this adapter deliberately preserves the raw JSON collection counts together with `TotalOperations` instead of importing the presentation scaling.

A null `BytesAllocatedPerOperation` remains missing. It is never converted to zero. A benchmark with zero operations and no observed memory diagnostics is rejected rather than producing manufactured zero evidence.

Timing statistics are intentionally not mapped in this first .NET slice. The raw JSON remains attached and hashed for later inspection, while shared-runner timing stays outside deterministic memory/allocation authority.

## Environment identity

The derived environment fingerprint includes the base environment plus:

- BenchmarkDotNet version;
- .NET runtime version;
- architecture;
- build configuration when available;
- .NET CLI version when available;
- the selected benchmark identity/job description and hardware-intrinsics description.

Changing those inputs makes memory evidence incomparable rather than silently treating different runtime/job configurations as equivalent.

## Provenance

The raw BenchmarkDotNet JSON is retained as a `benchmarkdotnet` artifact with its SHA-256 hash. The `dotnet.benchmarkdotnet` extension records the adapter contract, selected benchmark identity, operation count, and whether allocation telemetry was available.

## Usage

```sh
python scripts/convert_benchmarkdotnet.py \
  base-performance-evidence.json \
  BenchmarkDotNet.Artifacts/results/Benchmarks-report-full.json \
  --benchmark Example.TableBenchmarks.Materialize \
  --output performance-evidence.benchmarkdotnet.json
```

Use BenchmarkDotNet's JSON exporter with MemoryDiagnoser enabled in the producing .NET repository. That repository remains responsible for the benchmark scenario and any domain-specific semantic counters such as rows scanned/materialized or cache rebuilds.
