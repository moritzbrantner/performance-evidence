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

## Work amplification

Amplification ratios are explicit and domain-owned. The comparator does not guess that one counter should be divided by another. Callers declare a ratio as `NAME=NUMERATOR,DENOMINATOR`, and the comparison artifact records that definition together with baseline/candidate numerator values, denominator values, and the derived ratio.

The ratio remains unavailable when either source measurement is missing or changes definition across baseline/candidate. A zero denominator is reported as `undefined_zero_denominator`; a defined baseline ratio of zero keeps the absolute ratio delta but leaves its relative delta undefined.

The full raw measurement comparison remains alongside every derived amplification result, so a ratio never replaces its source evidence.

## CLI

```sh
python scripts/compare_evidence.py \
  baseline.json candidate.json \
  --expected-candidate-revision "$GITHUB_SHA" \
  --amplification physics.body_visits_per_changed_body=physics.body_visits,physics.changed_bodies \
  --output comparison.json
```

The comparator validates both source artifacts against the canonical Performance Evidence contract and validates its own generated comparison before writing it.
