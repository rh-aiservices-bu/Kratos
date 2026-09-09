# ADR-004: shared_state Dict for Inter-task Communication

## Status

Accepted

## Context

Tasks within a scenario need to pass data to subsequent tasks. For example:

- `provision_api_key` creates one or more API keys whose IDs and secrets must be available to `send_requests` and to the cleanup step.
- `apply_rate_limit_subscription` captures the original `MaaSSubscription` state so cleanup can restore it.
- `send_requests` records latency/error/throughput/token metrics so assertions can evaluate them.
- The background MaaS metrics poller (`ScenarioRunner._metrics_bg`, see ADR-014) reads raw metric values from Prometheus so assertion evaluation can reference and cross-check them.

Alternatives considered:

1. **Return values from `run()`**: tasks return structured data; the runner threads this data through to the next task's input.
2. **`TaskContext` attributes**: add typed fields to `TaskContext` for each category of shared data.
3. **Mutable `shared_state` dict on `TaskContext`**: tasks write to and read from an untyped dict.

## Decision

Use a **mutable `shared_state: dict` on `TaskContext`**. Tasks write to it under well-known keys and read from it by the same keys. The dict is passed by reference through the entire scenario, including cleanup.

Canonical keys:
| Key | Written by | Read by |
|---|---|---|
| `api_keys` | `provision_api_key` | `send_requests`, cleanup |
| `original_subscription` | `apply_rate_limit_subscription` | cleanup |
| `inference_results` | `send_requests` | assertion evaluation |
| `metrics` | background MaaS metrics poller (`ScenarioRunner`), `check_maas_metrics` | assertion evaluation |
| `metrics_baseline` | background MaaS metrics poller (`ScenarioRunner`) | `metrics` delta computation (see ADR-014) |

## Consequences

**Positive:**
- Zero boilerplate: adding a new inter-task data channel requires no changes to the `Task` ABC or `TaskContext` type.
- Both `run()` and `cleanup()` share the same dict — cleanup reliably finds what `run()` wrote.
- Easy to inspect/log the full `shared_state` at the end of a run for debugging.

**Negative:**
- No compile-time type checking on shared keys; a typo in a key name is a runtime error.
- Implicit coupling between tasks: a task that reads `shared_state["api_keys"]` silently has no keys if `provision_api_key` was not in the scenario and did not run before it.

**Neutral:**
- The well-known key table above serves as the contract; it should be kept up to date as new tasks are added.
- Scenario YAML validation (future work) could catch missing task dependencies before a run starts.
