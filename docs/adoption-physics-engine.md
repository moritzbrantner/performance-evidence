# Physics-engine dogfood

`physics-engine` is the first simulation/engine dogfood consumer for the canonical Performance Evidence contract.

## Consumer boundary

The engine owns its deterministic sandbox scenarios, correctness/replay checks, solver-work counters, and blocking performance policy. Its adapter emits one canonical document per sandbox case/trial plus diagnostic browser-session evidence. Performance Evidence owns the interchange schema and semantic validation; it does not reinterpret the physics counters or replace the engine's correctness gate.

Representative domain-owned induced-work counters include sampled events, contact/tail work, candidate pairs, broad-phase queries/rebuilds/reuse, response-scratch rebuilds, and stabilization work. Wall-clock step distributions remain outcomes rather than the sole explanation for a regression.

## Exact-head validation

Physics-engine PR #142 refreshed the consumer pin to Performance Evidence revision `068d880a1b76f41e06548c557af0a7bf8c8057eb`.

The exact PR head `7c612c54209c6f1bec9295b90d911ffecb7674f8` passed both:

- the ordinary physics `Validate` workflow; and
- the dedicated `Performance Evidence` workflow, including base/head WASM execution, canonical bundle packaging, checkout of the pinned Performance Evidence revision, schema/profile/semantic validation, and artifact preservation.

The consumer change was then merged to physics-engine as `dad05ff6f1d8d69e618d43999f1a4342e54c0b29`.

## Lesson for the contract

The useful integration shape is not a generic profiler taking over the scenario. The domain repository should emit its semantic work counters directly, while Performance Evidence provides the portable representation, comparison/budget semantics, and profiler adapters around that data.

This keeps optimization evidence close to the code that knows what a query, rebuild, candidate pair, contact, or stabilization pass actually means.
