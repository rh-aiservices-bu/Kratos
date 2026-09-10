# ADR-015: PromQL-Native Assertions

## Status

Accepted

## Context

`harness/result.py`'s match-form assertion (ADR-014) lets a scenario compare a MaaS-side metric against a harness-known count within a tolerance band, but the actual PromQL that produces the MaaS-side number lives one level removed from the assertion — in `MAAS_METRICS_QUERIES`, a JSON string in the *global* ConfigMap (`deploy/configmap-global.yaml`), decoupled from both the scenario YAML and the `assertions:` block that consumes it. Reading what a scenario like `metrics_fill` actually checks meant cross-referencing two files and two `harness/result.py` code paths (`_extract_metric`'s bare-name lookup, `_evaluate_match_assertion`'s `compare`/`to` dict).

The goal: make the PromQL itself the visible, authoritative definition of a MaaS-side assertion, right there in the scenario YAML, so a scenario author can write (and reason about) their own metric checks without needing a harness code change for every new comparison.

Two things stood in the way of just dropping raw PromQL text into `assertions:`:

1. **Isolating "this run's traffic."** No metric in the catalog (`docs/architecture/maas-metrics-reference.md`) carries a run-id or request-id label — the finest grain confirmed live is `limitador_namespace` (shared by every caller of that model route). ADR-014's baseline-delta approach solves this by subtracting a pre-run snapshot in Python, but a raw ad hoc PromQL query has no way to do that subtraction itself unless the snapshot is made available to it.
2. **Comparing against harness-side ground truth.** Half of what a match-form assertion checks (`inference_results.total_requests`, the harness's own sent-count) isn't a Prometheus metric at all — it's a Python value in `shared_state` that changes continuously as `send_requests` runs. PromQL can't reference it unless the harness makes it available as something PromQL can consume.

## Decision

**Named queries move into the scenario.** A scenario YAML gains an optional top-level `metrics_queries:` block — a dict of `name -> PromQL`, resolved for `${config.x}` the same way `assertions:`/task `params:` already are (`harness/config.py`). This replaces `MAAS_METRICS_QUERIES` in the global ConfigMap; `MAAS_METRICS_URL` stays global (cluster wiring, not scenario logic). The runner baseline-snapshots and background-polls these exactly as before ADR-015 — the only change is where they're declared.

```yaml
config:
  limitador_namespace: "llm/facebook-opt-125m-simulated-kserve-route"
metrics_queries:
  total_requests: 'sum(authorized_calls{limitador_namespace="${config.limitador_namespace}"})'
  total_tokens: 'sum(authorized_hits{limitador_namespace="${config.limitador_namespace}"})'
```

**New assertion form: `promql`.** Alongside the existing string form and the `compare`/`to` match form, an assertion may now be a dict containing a `promql` key:

```yaml
assertions:
  maas_requests_match:
    promql: >-
      abs(
        (sum(authorized_calls{limitador_namespace="${config.limitador_namespace}"}) - ${baseline.total_requests})
        - ${harness.inference_results.total_requests}
      )
      <= bool (${config.metrics_tolerance_pct} / 100 * clamp_min(${harness.inference_results.total_requests}, 1))
    expect: "== 1"
    max_wait_s: "${config.metrics_max_wait_s}"
```

`evaluate_assertion` (`harness/result.py`) dispatches to a new `_evaluate_promql_assertion` whenever `"promql"` is present in the spec dict (checked before the `compare`/`to` match-form branch, so the two stay mutually exclusive and both remain supported — this is additive, not a breaking change; no existing scenario needed to migrate). It reads the already-fetched value from `shared_state["metrics"][name]` and applies either `expect` (reusing the same `_EXPR_RE` operator grammar as the plain string form) or `compare_to`/`tolerance_pct` (the same tolerance-band math as `_evaluate_match_assertion`, for a promql LHS against a harness-side RHS). This function still never performs I/O — evaluation stays a pure, synchronous read of `shared_state`, exactly like every other assertion form; firing the query is the runner's job.

**Two new template variables, resolved on two different schedules.** `${config.x}` already resolves once at scenario load. This design adds:
- `${baseline.<name>}` — the pre-run snapshot of a named `metrics_queries` entry (`shared_state["metrics_baseline"][name]`), substituted once, immediately after the baseline fetch, before the background poller starts (`harness/runner.py:_substitute_baseline_vars`). This is what lets a `promql` assertion do its own delta subtraction in PromQL instead of relying on the harness's precomputed `{name}_delta`.
- `${harness.<namespace>.<key>}` — a live `shared_state` value (e.g. `inference_results.total_requests`), re-resolved on *every* poll tick, right before firing that tick's query (`harness/runner.py:_substitute_harness_vars`), since these values change continuously as tasks run. If a referenced value isn't populated yet, that tick's query is skipped entirely and the assertion stays PENDING, rather than substituting a placeholder.

Each `promql`-form assertion is fired as its own ad hoc instant query, merged into the same per-tick batch as the scenario's named `metrics_queries` (`harness/runner.py:_fetch_metrics_once` — `fetch_metrics` already accepts an arbitrary `{name: query}` dict, so no change was needed there). The result lands in `shared_state["metrics"][assertion_name]`, keyed by assertion name rather than a shared metric name. This means a `promql`-form assertion automatically participates in the same `_settle_and_evaluate()` poll-until-passing loop (ADR-014) as every other metrics-dependent assertion — no separate retry mechanism was needed.

**Result: match-form assertions can now be fully self-contained.** Combining `${baseline.x}` and `${harness.x}` with PromQL's `bool` comparison modifier collapses the entire cross-check — MaaS-side delta, harness-side ground truth, and the tolerance comparison itself — into one expression Prometheus evaluates directly, as shown in `scenarios/metrics_fill.yaml`. `compare`/`to`/`tolerance_pct` remain supported for scenarios that don't migrate; nothing forces the change.

## Consequences

**Positive:**
- What a MaaS-side assertion actually checks is now legible directly in the scenario YAML, in PromQL, without cross-referencing the global ConfigMap or a second `result.py` code path.
- Scenario authors can write new MaaS-vs-harness comparisons (or pure MaaS-side threshold checks) without a harness code change, as originally intended.
- Reuses ADR-014's baseline-snapshot, background-poll, and outcome-driven settle-retry machinery unchanged — no new execution model, no new failure modes to rediscover.
- Fully additive: existing `compare`/`to` scenarios keep working with zero changes.
- All five production scenarios' `send_requests` assertions were converted to `promql` form — including `error_rate_pct`/`p99_latency_ms`/`throughput_rps`, which are pure harness-side numbers with no real backing Prometheus metric, passed through as a bare `${harness.x}`-substituted literal (e.g. `promql: "${harness.inference_results.error_rate_pct}"`). This was deliberate: it exercises the real query-firing/parsing path against live Thanos Querier on every scenario run, not just `metrics_fill`'s genuine cross-check, catching bugs the single-scenario rollout wouldn't have. `direct_inference` keeps this form too even though it bypasses the MaaS gateway (no real MaaS-side metric applies there regardless of assertion form) — purely for coverage consistency, not because the check became meaningful.
- Doing this surfaced a real bug the original `metrics_fill`-only rollout never hit: a bare literal (no metric selector) evaluates to Prometheus's `scalar` result type (`{"resultType": "scalar", "result": [ts, "v"]}`) rather than `vector` (`{"result": [{"value": [ts, "v"]}]}`), and `harness/metrics_client.py:_extract_scalar` only parsed the latter — a pass-through query would have silently failed to parse (query "succeeds" but result is dropped, same as any other empty result, so the assertion just sits PENDING with no visible error). Fixed by having `_extract_scalar` branch on `resultType` rather than assuming one response shape; both are covered in `harness/tests/test_metrics_client.py`.
- Live-cluster testing found a second, more severe bug: `_substitute_baseline_vars` originally raised `KeyError` for *any* unresolvable `${baseline.x}` reference, whether the name was never declared (a real authoring typo) or was declared correctly but its baseline fetch simply came back with no data — e.g. `metrics_fill.yaml`'s `limitador_namespace` value was stale relative to the cluster's actual `DEFAULT_MODEL`, so `sum(authorized_calls{limitador_namespace="..."})` matched zero series. Since this substitution runs once, unguarded, before the task loop even starts, the latter case — an expected-to-happen environmental/config condition, not a code bug — crashed the *entire run* before a single task executed, with no clearer signal than an unhandled `KeyError` in the Job pod's logs. Fixed by distinguishing the two cases: an undeclared name still raises immediately (genuine typo, should fail loud and fast); a declared-but-empty result now returns `None` (permanently PENDING for that run, with a diagnostic log line pointing at the likely cause) instead of aborting everything else. Covered by `test_baseline_query_returning_no_data_does_not_crash_the_run` in `harness/tests/test_runner.py`.

**Negative:**
- Three assertion forms now exist in `harness/result.py` (string, match, promql) instead of two — ADR-014 already flagged "authors need to know when to use which form" as a cost, and this compounds it. Mitigated by `promql` being the more capable, self-documenting option going forward; the plain string and match forms remain for simple cases that don't need it.
- Two additional templating schedules (`${baseline.x}` once post-baseline, `${harness.x}` every poll tick) beyond `${config.x}`'s single load-time pass — a scenario author needs to know a `promql` field's `${...}` placeholders don't all resolve at the same time. `test_scenario_loads_and_resolves` (`harness/tests/test_scenarios.py`) was updated to allow `${baseline.` / `${harness.` to survive `load_scenario()` deliberately, rather than flagging them as leftover unresolved config.
- **Does not solve run-scoping.** `${baseline.x}`/`${harness.x}` are literal numeric substitutions into query text — they let PromQL arithmetic reference a harness number, they do not give Prometheus a label to filter "this run's traffic" by. The ADR-014 caveat stands unchanged: `authorized_calls`/`authorized_hits` aggregate every caller hitting that route, and isolation is still purely time-windowed (baseline-delta), not label-based. A scenario author writing a `promql` assertion needs to know this — it's called out in `CLAUDE.md`'s Assertions section for exactly that reason. Solving scoping for real would require the harness to push its own `run_id`-labeled metrics into Prometheus (e.g. via a Pushgateway) — a distinct, heavier feature, deliberately out of scope here.
- No new query-cost/complexity guardrails were added — `promql` text is still sent to Thanos verbatim with only the existing 5s per-request timeout. This remains acceptable only because scenario YAML stays an admin-authored/deployed artifact (ConfigMap), not something reachable through `KRATOS_CONFIG_OVERRIDES` (the UI-editable, non-admin path) — a `promql` field must never become overridable through that path.

**Neutral:**
- `MAAS_METRICS_QUERIES` is removed from `deploy/configmap-global.yaml`; `MAAS_METRICS_URL` stays.
- Supersedes the "Assertion format extension" section of ADR-014 as the current description of `harness/result.py`'s dict-form assertions, without invalidating ADR-014's baseline-delta/settle-retry decisions, which this builds on directly.
