# CI artifact reuse profile

`ci-artifact-reuse/v1` normalizes the economics of one exact-head reusable build artifact.

The authoritative build identity remains the reusable-workflows execution receipt. This profile only maps observed computational cost into Performance Evidence so tooling can compare setup, build, upload, artifact size, and expected fan-out without inventing repository-specific semantics.

## Classification

- **Useful work:** the immutable artifact bytes and the number of equivalent downstream consumers served by those bytes.
- **Induced work:** producer setup, artifact construction, upload, and related transport overhead.
- **Outcome:** estimated build time avoided when equivalent consumers reuse one verified artifact rather than rebuilding it.

The producer's `recommended` field is advisory. It must not grant reuse eligibility, merge eligibility, or release authority. Exact source SHA, artifact identity, receipt validation, and digest verification remain separate correctness/provenance checks.

Consumer materialization time and bytes may be attached as additional observations by the execution layer. They should be compared against the producer's avoided-build estimate before broad rollout.

## Adoption rule

A repository should normally adopt artifact reuse only when:

1. the artifact has multiple semantically equivalent consumers;
2. the artifact is immutable and exact-head verifiable;
3. build/setup cost is material relative to verified transfer overhead; and
4. consumer workflows can preserve their own semantic validation boundaries.

Cheap builds or outputs with different configuration/authority should continue to recompute locally.
