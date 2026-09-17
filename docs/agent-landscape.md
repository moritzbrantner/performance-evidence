# Agent landscape integration

Performance Evidence is a shared evidence contract, not an orchestrator, profiler UI, or agent protocol. The integration model keeps those authorities separate so repositories can use performance evidence directly in local/CI workflows and also pass the same immutable evidence through the wider agent landscape when needed.

## Ownership map

| Concern | Authority | Integration with Performance Evidence |
| --- | --- | --- |
| Domain scenario and counter meaning | Producing repository | Emits useful-work, induced-work, and outcome measurements using domain-owned names and semantics. |
| Canonical computational-cost payload | `performance-evidence` | Defines portable evidence, comparison semantics, budgets, and adapter contracts. |
| Profiling capture and rich exploration | `runtime-profiler` | Produces or ingests canonical evidence and links profiler-specific artifacts without becoming the interchange authority. |
| Repository capability discovery and validation | `coding-tooling` | Discovers a repository component and invokes its declared performance/evidence capability. It does not interpret performance results. |
| Hosted deterministic execution | `reusable-workflows` | Runs the declared exact-head capability and preserves machine-readable artifacts/receipts. |
| Neutral cross-component evidence reference | `agent-contracts` | `agent.evidence/v1` may reference an immutable Performance Evidence artifact by URI and digest when evidence crosses an independently owned boundary. |
| Durable scheduling and run state | `agent-loop-orchestrator` | May store evidence references on orchestrated runs. Direct local/CI evidence capture does not require orchestration. |
| Performance diagnosis and architecture review | `coding-agent-skills` | Consumes exact-head/baseline evidence and correlates measured work amplification with code/dataflow changes. |

## Direct repository path

The simplest path stays local to the repository:

1. The repository owns a deterministic scenario and its semantic counters.
2. A repository command emits `performance-evidence.json`.
3. `coding-tooling` discovers that declared capability and invokes it.
4. Local CI or `reusable-workflows` preserves the canonical artifact.
5. A human or coding agent consumes the artifact directly.

This path does not require `agent-loop-orchestrator`, `agent-contracts`, or `runtime-profiler` when their extra capabilities are not needed.

## Cross-component path

When evidence crosses an independently owned system boundary:

1. Preserve the canonical Performance Evidence artifact unchanged.
2. Store it at an immutable or content-addressed location.
3. Compute and preserve its digest.
4. Wrap the artifact location and digest in the neutral `agent.evidence/v1` reference owned by `agent-contracts`.
5. Pass that reference to an orchestrator, evaluator, or other agent component.

The neutral reference is an envelope around evidence, not a replacement schema. Consumers that need computational-cost semantics resolve the reference and validate the referenced Performance Evidence payload.

## Integration invariants

- Do not copy `agent-contracts` schemas into this repository as a second authority.
- Do not require orchestration for direct CLI, CI, or coding-agent use.
- Do not make `runtime-profiler` the owner of comparison or budget semantics.
- Do not let `coding-tooling` infer performance meaning from command success alone; command success only establishes that evidence collection/validation completed.
- Do not convert missing or incomparable evidence into a passing comparison.
- Do not infer a performance win from code shape. Integration decisions that rely on performance must use evidence from the exact reviewed head and a comparable baseline.
- Keep profiler-native traces, flamegraphs, heap captures, and browser traces as linked artifacts; the canonical evidence record carries the portable measurements and provenance.

## Capability shape

Repositories should expose stable repository-owned commands through `.coding-tooling.json` rather than relying on language-specific guessing. Performance Evidence itself dogfoods this pattern with deterministic validation and evidence-emission commands. Adapters may later provide reusable helpers, but the consuming repository remains authoritative for the scenario that was executed and the semantic work counters it emits.

A future reusable workflow can standardize artifact preservation and optional `agent.evidence/v1` reference emission after the canonical artifact validates. That workflow should consume this contract rather than introducing a parallel performance schema.
