# ADR-013: Real-time Assertion Evaluation During Run Execution

## Status

Accepted

## Context

Assertions define the pass/fail criteria for a scenario run (e.g. `error_rate_pct: "< 5"`, `p99_latency_ms: "< 10000"`). A decision must be made about *when* assertions are evaluated during a run and *how* results are surfaced to the operator.

Three approaches were considered:

1. **Batch evaluation at run end**: all tasks execute to completion, then all assertions are evaluated once. The operator sees only the final verdict.
2. **Evaluation after each task completes**: assertions are re-evaluated each time a task's `run()` returns. Granularity is per-task, not per-operation within a task.
3. **Continuous evaluation within tasks**: tasks update `shared_state` after every atomic operation (e.g. after every individual inference request in `send_requests`) and trigger assertion re-evaluation immediately. The operator sees metrics and assertion state update on every request, not just when the full task finishes.

Kratos already streams task log output to the browser in real-time via SSE (ADR-007). Option 3 extends this to assertion state with the finest possible granularity.

## Decision

Evaluate assertions **continuously within tasks** — after every atomic operation that updates `shared_state`. In `send_requests`, this means after every individual inference request completes (regardless of concurrency): the task updates its running metrics in `shared_state` (latency, error count, throughput) and emits an assertion re-evaluation event via SSE.

Tasks are responsible for calling a shared `emit_assertion_state(ctx)` helper after each operation that produces new metric data. The helper re-evaluates the full assertion suite against the current `shared_state` and emits a structured SSE event. Tasks that do not produce rolling metrics (e.g. `provision_api_key`, `apply_rate_limit_subscription`) call it once on completion.

Intermediate assertion state distinguishes three states per assertion:
- **Pending** — the metric has not yet been produced (task hasn't run yet)
- **Passing** — metric is present and the threshold is met
- **Failing** — metric is present but the threshold is not met

The UI renders a live assertion status panel that updates continuously as requests are fired. The final PASS/FAIL verdict is the assertion state after the last task completes.

## Consequences

**Positive:**
- Operators see assertion outcomes updating after every request, not just at task or run boundaries. A drifting error rate or latency spike is visible as it develops.
- For long-running scenarios (large request counts), a clearly failing assertion mid-run gives the operator the information needed to cancel early rather than waiting for all requests to complete.
- No architectural additions needed: the existing SSE channel (ADR-007) carries both log lines and assertion state events.

**Negative:**
- Tasks must actively call `emit_assertion_state(ctx)` after each operation — this is a convention, not enforced by the `Task` ABC. A task that forgets to call it will appear to have no intermediate updates.
- High-frequency emission (e.g. 1000 requests at concurrency 20) could produce a large number of SSE events. The implementation should debounce or batch assertion events (e.g. emit at most every 100ms or every N completed requests) to avoid overwhelming the SSE channel.
- The `ScenarioRunner` must distinguish "pending" from "failing" — requires slightly more logic than a simple end-of-run batch evaluation.

**Neutral:**
- The final verdict (PASS/FAIL written to SQLite and the results JSON) is always based on the assertion state at run completion, not any intermediate state.
- Cleanup runs regardless of intermediate assertion state — only the final verdict influences how the run is recorded.
