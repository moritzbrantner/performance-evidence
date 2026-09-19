# Application counter bridge

The `application-counters/v1` bridge makes repository-owned semantic counters cheap to attach to canonical Performance Evidence without defining another counter vocabulary.

The input is only a fragment of the existing canonical `measurements` object:

```json
{
  "useful_work": [
    {
      "name": "simulation.state_changes",
      "value": 3,
      "unit": "count",
      "measurement_type": "counter"
    }
  ],
  "induced_work": [
    {
      "name": "simulation.entity_visits",
      "value": 120,
      "unit": "count",
      "measurement_type": "counter"
    }
  ],
  "outcomes": []
}
```

There is no centrally owned list of application counters. A physics engine decides what a body visit or contact test means; a table implementation decides what materialization means. The bridge only validates the same measurement objects already used by the canonical evidence contract and rejects duplicate names or collisions.

Typical repository-owned counters include traversals, materializations, snapshots, recomputations, cache rebuilds, bytes moved, and semantic changes.

## Disabled instrumentation

An empty fragment is a strict adapter no-op: merging it returns the base evidence unchanged, with no artifact or extension added. This gives instrumentation implementations a deterministic representation for “disabled” without manufacturing zero counters.

The bridge itself cannot prove that a language-specific counter implementation has no runtime side effects when disabled. That remains an implementation property to verify in the producing repository.

## Provenance

A non-empty counter fragment is retained as a hashed `application-counters` artifact and described by the `application.counters` extension. Scenario, workload, source, environment, and pre-existing measurements remain unchanged.

## Usage

```sh
python scripts/merge_application_counters.py \
  base-performance-evidence.json \
  semantic-counters.json \
  --output performance-evidence.with-counters.json
```

Applications may emit the fragment however is natural for their language. They do not need to depend on a Performance Evidence runtime library.
