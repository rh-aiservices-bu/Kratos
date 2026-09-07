# ADR-003: Task ABC with Deferred, Scenario-wide Cleanup

## Status

Accepted

## Context

Tasks create side effects in the MaaS environment: API keys are provisioned, `MaaSSubscription` CRs are patched, inference requests leave traces in the metrics pipeline. These side effects need to be cleaned up after a run to avoid polluting the environment with test artifacts.

Two cleanup strategies were considered:

1. **Per-task cleanup (RAII-style)**: each task cleans up immediately after it completes (or fails), before the next task starts.
2. **Deferred cleanup**: all tasks run first (pass or fail), then every task's `cleanup()` is called in sequence at the very end of the scenario.

A related question is whether cleanup is part of the `Task` contract or a separate orchestration concern.

## Decision

Cleanup is part of the **`Task` ABC**:

```python
class Task(ABC):
    async def run(self, ctx: TaskContext) -> TaskResult: ...
    async def cleanup(self, ctx: TaskContext) -> None: ...
```

Cleanup is **deferred**: the `ScenarioRunner` calls `run()` on all tasks in order, then calls `cleanup()` on all tasks in reverse order regardless of whether the scenario passed or failed. Cleanup failures are logged but do not change the run's pass/fail status.

## Consequences

**Positive:**
- Accumulated state is observable before cleanup. For example, `multi_key_load` provisions N keys, sends requests through all of them, then bulk-revokes — an operator can inspect the key pool in the MaaS UI between task completion and cleanup if they act quickly.
- Cleanup always runs: a task failure mid-scenario does not leave orphaned resources.
- The cleanup contract is co-located with the task logic, making it easy to reason about what a task creates and what it removes.

**Negative:**
- Resources created early in a scenario persist through all subsequent tasks, including potentially slow ones (e.g. a large inference burst). This is intentional but means test artifacts live longer than with per-task cleanup.
- A cleanup failure is silent at the pass/fail level; operators must check logs to discover leaked resources.

**Neutral:**
- `TaskContext.shared_state` is available during cleanup so tasks can find the IDs of resources they created (e.g. `shared_state["api_keys"]` for bulk revocation, `shared_state["original_subscription"]` for restoring CRD state).
