# Weekly agent efficiency rollup

The weekly rollup is a derived view over canonical `agent-run/v1` Performance Evidence artifacts. It does not replace the `agent-loop-orchestrator` execution ledger or its richer efficiency report.

## Input

The rollup consumes one directory tree containing canonical Performance Evidence documents for `scenario.id = agent/implementation-attempt`.

Only measurements defined by the `agent-run/v1` profile participate in the standard summary. Missing measurements remain missing; they are never interpreted as zero.

## Summary

The machine-readable rollup reports:

- attempt and accepted-candidate counts;
- token totals for input, output, and cached input when observed;
- total observed provider cost in USD when observed;
- mean and median agent execution time when observed;
- mean and median deterministic time-to-green when observed;
- counts by provider, model, outcome, and escalation reason;
- telemetry coverage counts so partial token/cost/time data cannot look complete accidentally.

Provider/model/outcome/escalation metadata comes from the namespaced `agent.execution` extension. Provider session identifiers remain excluded.

## Authority boundary

The rollup is analytical output. Raw canonical attempt evidence remains the portable authority for computational-cost semantics, while `agent-loop-orchestrator` remains authoritative for task/run state and its execution ledger.

A weekly automation may retain both artifacts: the richer orchestrator report for operational investigation and this canonical rollup for cross-agent/model/runtime trend analysis.
