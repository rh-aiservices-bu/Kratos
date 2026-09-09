# ADR-010: Scenario YAML with Inline Assertions

## Status

Accepted

## Context

Scenarios need a way to define pass/fail criteria. Options considered:

1. **Hard-coded per-scenario thresholds in Python**: each scenario class defines its own assertions in code. Inflexible; changing a threshold requires a code change and image rebuild.
2. **Assertions as a separate config file**: a parallel YAML or JSON file per scenario. Adds file management overhead with no clear benefit over inline assertions.
3. **Inline `assertions:` block in the scenario YAML**: pass/fail thresholds are declared in the same file that defines the scenario's tasks and config. Scenario YAML is self-contained.

## Decision

Scenario YAML files include an **`assertions:` block** with metric/threshold pairs. The format is:

```yaml
assertions:
  metric_name: "<operator> <value>"
```

Supported operators: `<`, `>`, `<=`, `>=`, `==`.

Assertions are evaluated **continuously within tasks** — after every atomic operation that produces new metric data (e.g. after every individual inference request in `send_requests`). Tasks emit assertion state updates via SSE after each operation. This means the operator sees assertion outcomes updating live as requests are fired, not only at task or run completion. See ADR-013 for the full decision on evaluation granularity and SSE emission debouncing. The final PASS/FAIL verdict is determined after all tasks have completed and the last assertion evaluation has run. Assertion values may reference scenario config params via interpolation (e.g. `"<= ${config.rate_limit_rps}"`).

Available metrics for assertion (populated by task execution):
- From `send_requests` → `shared_state["inference_results"]`: `error_rate_pct`, `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms`, `throughput_rps`, `total_requests`, `success_count`, `fail_count`, `total_tokens_sent`, `prompt_tokens_sent`, `completion_tokens_sent`
- From the background MaaS metrics poller → `shared_state["metrics"]`: `total_requests`, `total_tokens` (raw, as reported by the configured Prometheus queries) and `total_requests_delta`, `total_tokens_delta` (relative to the run's baseline snapshot)

A second, structured assertion form supports comparing two live metrics to each other with a tolerance band — see ADR-014 for the format and rationale (`compare`/`to`/`tolerance_pct`).

## Consequences

**Positive:**
- Scenario files are fully self-contained: a reader can understand the task chain, default parameters, and pass/fail criteria from a single YAML file.
- Adding or changing thresholds is a YAML edit, not a code change — no image rebuild required.
- The assertion format is simple and readable (`error_rate_pct: "< 5"`) without needing a custom DSL.
- Referencing config params in assertion values (`"<= ${config.rate_limit_rps}"`) keeps rate-limit scenarios consistent without magic numbers.

**Negative:**
- The `${config.<key>}` interpolation in assertion values must be evaluated at assertion time (after config is loaded), which means the harness config loader and assertion evaluator must share the resolved config.
- Complex assertions (e.g. "p99 increases by less than 20% under 2× concurrency") are not expressible in this format. Such scenarios would require a dedicated task or a more capable assertion DSL (future work).

**Neutral:**
- If no `assertions:` block is defined, the run is considered `PASS` as long as no task raised an exception. This is intentional for exploratory scenarios.
