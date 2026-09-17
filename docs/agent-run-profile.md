# Agent run evidence profile

`profiles/agent-run-v1.json` defines the portable Performance Evidence vocabulary for one coding-agent implementation attempt. It is intentionally a profile over the canonical `performance-evidence.json` contract rather than a second agent telemetry format.

## Ownership

- `agent-loop-orchestrator` owns durable task/run state, provider events, attempts, CI references, escalation decisions, and the raw execution ledger.
- `performance-evidence` owns the portable measurement names, classification, units, provenance rules, and comparison semantics used when agent computational cost is exported for analysis.
- `coding-harness` and `coding-tooling` remain execution/validation authorities. They may contribute deterministic command evidence, but they do not become token-accounting stores.
- `runtime-profiler` may visualize or aggregate these artifacts but does not redefine them.
- `agent-contracts` may reference the immutable artifact across component boundaries; it does not copy these measurements into a competing schema.

## One attempt, one evidence record

The profile maps one orchestrator attempt to one canonical evidence record. This keeps comparison semantics precise: a provider/model switch, resumed session, retry, or escalation remains a distinct execution attempt rather than being silently averaged together.

The stable scenario ID is `agent/implementation-attempt`. Workload identity should represent the logical task plus project and baseline revision. Run IDs, attempt numbers, provider/model choices, timing, cost, and usage must not contribute to the workload hash; otherwise equivalent attempts would become incomparable merely because the execution strategy changed.

## Measurement classification

The initial profile defines:

- `agent.candidate_produced` as useful work: whether the attempt produced a candidate revision;
- `agent.input_tokens`, `agent.output_tokens`, and `agent.cached_input_tokens` as induced work;
- `agent.execution_time`, `agent.deterministic_time_to_green`, and `agent.cost` as outcomes.

Missing telemetry remains missing. Adapters must not coerce unavailable token, cost, or time-to-green values to zero.

`totalTokens` is deliberately not canonical in v1 because it is derivable only when the provider's accounting semantics are known. Preserve the raw provider value in the source ledger if needed; do not assume cached-token inclusion rules are identical across providers.

## Mapping from agent-loop-orchestrator

The current `agent-loop-efficiency` report already exposes the required raw fields:

| Performance Evidence | Orchestrator field |
| --- | --- |
| source revision | `baselineSha` |
| candidate output | `candidateSha` |
| provider/model | `provider`, `model` |
| attempt identity | `taskId`, `runId`, `attemptNumber` |
| execution duration | `executionMs` |
| deterministic time-to-green | `deterministicTimeToGreenMs` |
| input/output/cached tokens | `usage.inputTokens`, `usage.outputTokens`, `usage.cachedInputTokens` |
| monetary cost | `usage.costUsd` |
| environment evidence | `environment` |
| CI correlation | `ciRunIds` |

The baseline revision is the source revision for the attempt. `candidateSha` describes an output of the attempt and therefore does not replace the baseline source revision.

An adapter must only emit `source.dirty = false` when the producing execution layer establishes that the attempt started from the exact clean baseline revision. If that invariant is not available, the adapter must fail or collect the missing provenance rather than inventing cleanliness.

## Metadata extension

Execution metadata that is important for routing analysis but is not itself a numeric performance measurement belongs in `extensions["agent.execution"]`:

- task/run/project identifiers;
- provider and model;
- attempt number and outcome;
- failure/escalation reason;
- whether a provider session was resumed;
- CI run IDs.

Provider session IDs are intentionally excluded from portable artifacts. They are operational ledger identifiers and may be sensitive or reusable; they are not required for performance comparison.

## Environment identity

The canonical environment fingerprint should be derived deterministically from semantic execution-environment evidence already produced by the orchestrator. Provider/model may be included when they materially define execution behavior. Raw host names, timestamps, temporary paths, session IDs, credentials, or other ambient state must not affect the fingerprint.

## Next integration steps

1. Teach `agent-loop-orchestrator` to export each attempt using this profile while retaining its richer efficiency report as the ledger/rollup view.
2. Let weekly efficiency reporting aggregate canonical attempt evidence by workload, provider/model, escalation stage, and outcome.
3. Apply Slice 2 comparison semantics to equivalent attempts so routing changes can be evaluated without hiding zero or missing baselines.
4. Later expose the same immutable artifacts to architecture-review and repository-convergence skills when token/time cost is relevant to choosing or calibrating an execution path.
