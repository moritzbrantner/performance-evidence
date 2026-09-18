# Performance Evidence comparison

`schema/performance-comparison.schema.json` defines the derived comparison artifact for one candidate evidence document and one baseline evidence document. The original Performance Evidence artifacts remain authoritative; comparison never rewrites their measurements.

## Comparability

A comparison is fail-closed when either input is dirty, the scenario or workload identity differs, the environment fingerprint differs, an explicitly expected candidate revision does not match, or the candidate declares a different baseline revision/digest.

For merge or integration decisions, callers should pass the reviewed head through `--expected-candidate-revision`. This binds the candidate evidence to the exact revision under review without making this repository responsible for discovering Git state.

Missing measurements remain missing. A measurement present on only one side is marked `missing_baseline` or `missing_candidate`; it is never coerced to zero. Measurements with the same name but different group, unit, or measurement type are `incompatible_definition`.

## Deltas

Comparable measurements preserve both raw snapshots and add:

- `absolute_delta = candidate - baseline`;
- `relative_delta.value = (candidate - baseline) / baseline` when the baseline is non-zero.

A zero baseline keeps the absolute delta but reports `relative_delta.status = undefined_zero_baseline` with a null value. This avoids manufacturing infinity or an arbitrary percentage.

If the scenario as a whole is incomparable, raw measurement snapshots are still preserved for diagnosis, but all measurement deltas are unavailable.

## CLI

```sh
python scripts/compare_evidence.py \
  baseline.json candidate.json \
  --expected-candidate-revision "$GITHUB_SHA" \
  --output comparison.json
```

The comparator validates both source artifacts against the canonical Performance Evidence contract and validates its own generated comparison before writing it.
