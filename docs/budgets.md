# Performance Evidence budgets

Performance Evidence budget policies apply thresholds to a validated comparison artifact. They do not run correctness tests, collect measurements, or retry failed scenarios. The producing repository remains responsible for the scenario and semantic counters; the comparison artifact remains the authoritative before/after evidence.

## Modes

Each rule chooses one mode:

- `hard`: may fail or block CI. Hard rules are restricted to comparable deterministic work evidence. Outcome measurements and timing/rate measurements are not eligible for hard gating.
- `informational`: evaluates the threshold and reports a breach without affecting the aggregate pass/fail result.
- `calibration`: records the same threshold observation for noisy or environment-sensitive metrics without making it merge authority.

This keeps wall-clock time useful without making a noisy runner decide whether a change is correct to merge.

## Assertions

Rules can evaluate:

- `candidate_max`: the candidate value must not exceed a fixed maximum;
- `absolute_regression_max`: `candidate - baseline` must not exceed a maximum regression;
- `relative_regression_max`: the normalized comparison delta must not exceed a maximum regression.

A missing target, incomparable measurement, zero-baseline relative delta, or otherwise unavailable value is never converted to zero. For a hard rule it blocks evaluation rather than passing.

## Exact head and retries

Budget policies require:

```json
{
  "execution": {
    "require_exact_head": true,
    "automatic_retries": 0
  }
}
```

The evaluator verifies that the comparison is comparable and carries `expected_candidate_revision` equal to the candidate source revision. A hard budget cannot be applied to a comparison that was not bound to the reviewed head.

`automatic_retries: 0` is part of the portable CI policy. Execution layers should run the authoritative scenario once for a revision. An explicit human rerun produces new evidence and must not silently overwrite or average away the failed exact-head result.

## Correctness boundary

Performance budgets complement correctness validation; they do not replace it. Correctness tests answer whether behavior is valid. Performance Evidence answers how much useful and induced work the valid behavior performs. CI should keep those authorities as separate checks even when both consume the same exact source revision.

## CLI

First produce a comparison, then evaluate a policy:

```sh
python scripts/compare_evidence.py \
  baseline.json candidate.json \
  --expected-candidate-revision "$GITHUB_SHA" \
  --amplification physics.body_visits_per_changed_body=physics.body_visits,physics.changed_bodies \
  --output comparison.json

python scripts/evaluate_budget.py \
  performance-budget.json comparison.json \
  --output budget-evaluation.json
```

Exit codes are:

- `0`: hard budget passes;
- `2`: hard budget fails or is blocked by unavailable/ineligible/mismatched evidence;
- `1`: malformed policy, malformed comparison, or evaluator error.

Informational and calibration threshold breaches remain visible in the machine-readable evaluation but do not change a passing hard-gate exit code.
