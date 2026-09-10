import asyncio
import contextlib
import json
import os
import re
import time
import traceback
from pathlib import Path

_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
_RESULTS_DIR = _DATA_DIR / "results"


def _read_sa_token(config: dict) -> str:
    if token := config.get("SA_TOKEN", ""):
        return token
    try:
        return Path(_SA_TOKEN_PATH).read_text().strip()
    except OSError:
        return ""

from harness.config import load_scenario
from harness.metrics_client import fetch_metrics
from harness.result import (
    AssertionResult,
    RunResult,
    TaskResult,
    compute_run_status,
    evaluate_all_assertions,
)
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_EMIT_DEBOUNCE_S = 0.1
# Default cap for settling a metrics-dependent assertion (see _settle_and_evaluate).
# Confirmed on the cluster this repo targets: Prometheus/Thanos scrapeInterval is 30s
# cluster-wide (no per-target override on the Limitador PodMonitor), so a request
# landing right after a scrape must wait nearly the full 30s for the next one — 65s
# leaves real headroom above that for scrape jitter/an occasional delayed scrape under
# load. Override per-scenario via an assertion's `max_wait_s` (see _configured_max_wait_s
# below) if a cluster's interval differs or needs more headroom.
#
# Earlier designs tried to detect "has a fresh scrape landed" indirectly — comparing
# fetched values against a baseline, against the previous poll, against the Prometheus
# response's own timestamp — and each broke on a different, increasingly subtle
# Prometheus API behavior (see ADR-014 for the full history). This settles that by
# checking the only thing that actually matters directly: does the assertion pass yet.
_METRICS_FINAL_MAX_WAIT_S = 65.0
_METRICS_FINAL_POLL_INTERVAL_S = 5.0


def _configured_max_wait_s(assertions: dict, task_defs: list[dict]) -> float:
    """Largest `max_wait_s` set on any match-form assertion (top-level or per-task).

    All match-form assertions share the one background metrics fetch/retry loop, so
    a single scenario-wide value is used — take the max across whatever's configured,
    falling back to the module default when nothing overrides it.
    """
    values = [
        float(spec["max_wait_s"])
        for spec in assertions.values()
        if isinstance(spec, dict) and "max_wait_s" in spec
    ]
    for task_def in task_defs:
        values.extend(
            float(spec["max_wait_s"])
            for spec in (task_def.get("assertions") or {}).values()
            if isinstance(spec, dict) and "max_wait_s" in spec
        )
    return max(values) if values else _METRICS_FINAL_MAX_WAIT_S


# Template variables a promql-form assertion can reference, in addition to
# ${config.x} (already resolved by harness/config.py at scenario-load time, before
# either regex below ever sees the text):
#   ${baseline.<name>}          — a name from this scenario's metrics_queries, as
#                                  snapshotted before the task loop started
#   ${harness.<namespace>.<key>} — a live shared_state value (e.g.
#                                  inference_results.total_requests)
# See ADR-015 for why these resolve on two different schedules (baseline once,
# harness every poll tick) rather than both being handled by config.py's loader.
_BASELINE_VAR_RE = re.compile(r"\$\{baseline\.([A-Za-z0-9_]+)\}")
_HARNESS_VAR_RE = re.compile(r"\$\{harness\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}")


def _collect_promql_assertions(assertions: dict, task_defs: list[dict]) -> dict[str, str]:
    """Return {assertion_name: promql_template} for every promql-form assertion,
    scenario-level and per-task, so the runner can poll each as its own ad hoc query
    alongside the scenario's named metrics_queries.
    """
    collected: dict[str, str] = {}
    for name, spec in assertions.items():
        if isinstance(spec, dict) and "promql" in spec:
            collected[name] = spec["promql"]
    for task_def in task_defs:
        for name, spec in (task_def.get("assertions") or {}).items():
            if isinstance(spec, dict) and "promql" in spec:
                collected[name] = spec["promql"]
    return collected


def _substitute_baseline_vars(
    template: str, baseline: dict[str, float], declared: set[str]
) -> str | None:
    """Resolve ${baseline.<name>} references against the pre-run metrics snapshot.

    Runs once, right after the baseline fetch — unlike ${harness.*}, baseline values
    never change during a run, so there's no need to re-resolve them on every tick.

    Two distinct failure modes here, handled differently on purpose:
    - ${baseline.<name>} where <name> isn't declared in this scenario's
      metrics_queries at all is an authoring mistake (a typo, or a forgotten
      metrics_queries entry) — raises immediately, loud, at scenario start, the same
      way a bad ${config.x} reference already does.
    - <name> IS declared, but its baseline fetch came back with no data — e.g. a
      label filter (like limitador_namespace) that doesn't match any series on this
      cluster. That's an expected-to-happen environmental/config condition, not a
      code bug, and must not crash the entire run before a single task executes (as
      it did previously) — every other "metric not populated yet" case in this
      codebase degrades to PENDING instead, so this does too: returns None, telling
      the caller to permanently skip firing this assertion's query (the baseline
      never gets re-fetched), and logs why so it's diagnosable instead of silent.
    """
    unresolved: set[str] = set()

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in declared:
            raise KeyError(
                f"${{baseline.{key}}} referenced but {key!r} is not declared in "
                f"this scenario's metrics_queries: {sorted(declared)}"
            )
        if key not in baseline:
            unresolved.add(key)
            return ""
        return str(float(baseline[key]))

    resolved = _BASELINE_VAR_RE.sub(_sub, template)
    if unresolved:
        print(
            f"[runner] baseline metrics {sorted(unresolved)} returned no data at "
            "scenario start (check the query's label filters against what's "
            "actually live on this cluster, e.g. via /api/v1/series) — any "
            "assertion referencing ${baseline." + next(iter(unresolved)) + "} will "
            "stay PENDING for this run",
            flush=True,
        )
        return None
    return resolved


def _substitute_harness_vars(template: str, shared_state: dict) -> str | None:
    """Resolve ${harness.<namespace>.<key>} references against live shared_state.

    Unlike ${config.x}/${baseline.x} (resolved once), these change continuously
    during a run, so this re-runs on every poll tick right before firing the query.
    Returns None if any referenced value isn't populated yet — tells the caller to
    skip firing this tick's query entirely (the assertion stays PENDING) rather than
    substituting a bogus placeholder value.
    """
    missing = False

    def _sub(m: re.Match) -> str:
        nonlocal missing
        namespace, key = m.group(1), m.group(2)
        ns = shared_state.get(namespace, {})
        if not isinstance(ns, dict) or key not in ns:
            missing = True
            return ""
        return str(float(ns[key]))

    resolved = _HARNESS_VAR_RE.sub(_sub, template)
    return None if missing else resolved


class ScenarioRunner:
    def __init__(self, scenario_path: str, run_id: str) -> None:
        self.scenario_path = scenario_path
        self.run_id = run_id
        self._last_emit: float = 0.0

    async def run(self) -> RunResult:
        scenario = load_scenario(self.scenario_path)
        scenario_name: str = scenario["name"]
        config: dict = scenario.get("_resolved_config", {})
        assertions: dict[str, str | dict] = scenario.get("assertions") or {}
        task_defs: list[dict] = scenario.get("tasks") or []
        shared_state: dict = {}

        def _assertion_dict(r: object, task_name: str | None) -> dict:
            return {
                "task": task_name,
                "name": r.name,  # type: ignore[attr-defined]
                "status": r.status,  # type: ignore[attr-defined]
                "value": r.current_value,  # type: ignore[attr-defined]
                "expected_value": r.expected_value,  # type: ignore[attr-defined]
                "expression": r.expression,  # type: ignore[attr-defined]
            }

        def _write_assertions(
            completed_task_results: list,
            current_task_name: str | None,
            current_task_assertion_results: list,
            global_assertion_results: list,
        ) -> None:
            """Write current assertion state to the dedicated PVC file."""
            payload = (
                [_assertion_dict(r, tr.task_name) for tr in completed_task_results for r in tr.assertions]
                + [_assertion_dict(r, current_task_name) for r in current_task_assertion_results]
                + [_assertion_dict(r, None) for r in global_assertion_results]
            )
            try:
                _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                (_RESULTS_DIR / f"{self.run_id}-assertions.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            except OSError as exc:
                print(f"[runner] could not write assertions: {exc}", flush=True)

        task_completed_progress: dict[str, dict] = {}

        def _write_progress(current_idx: int, completed: list[TaskResult]) -> None:
            """Write current task progress to the dedicated PVC file."""
            task_list = []
            for i, task in enumerate(tasks):
                if i < len(completed):
                    chip_status = "DONE" if completed[i].status == "PASS" else "FAIL"
                    entry: dict = {"name": task.name, "status": chip_status}
                    cp = task_completed_progress.get(task.name)
                    if cp:
                        entry["progress"] = cp
                    task_assertions = completed[i].assertions
                    if task_assertions:
                        if any(a.status == "FAILING" for a in task_assertions):
                            entry["assertions_status"] = "FAILING"
                        elif all(a.status == "PASSING" for a in task_assertions):
                            entry["assertions_status"] = "PASSING"
                        else:
                            entry["assertions_status"] = "PENDING"
                    task_list.append(entry)
                elif i == current_idx:
                    entry: dict = {"name": task.name, "status": "RUNNING"}
                    tp = shared_state.get("task_progress")
                    if tp:
                        entry["progress"] = tp
                    task_list.append(entry)
                else:
                    task_list.append({"name": task.name, "status": "PENDING"})
            try:
                _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                (_RESULTS_DIR / f"{self.run_id}-progress.json").write_text(
                    json.dumps({"tasks": task_list}), encoding="utf-8"
                )
            except OSError as exc:
                print(f"[runner] could not write progress: {exc}", flush=True)

        current_task_assertions: dict[str, str | dict] = {}

        async def emit() -> None:
            now = time.monotonic()
            if now - self._last_emit < _EMIT_DEBOUNCE_S:
                return
            self._last_emit = now
            task_name = tasks[current_task_idx].name if current_task_idx >= 0 else None
            _write_assertions(
                completed_task_results=task_results,
                current_task_name=task_name,
                current_task_assertion_results=evaluate_all_assertions(current_task_assertions, shared_state),
                global_assertion_results=evaluate_all_assertions(assertions, shared_state),
            )
            _write_progress(current_task_idx, task_results)

        sa_token = _read_sa_token(config)
        metrics_url: str = config.get("MAAS_METRICS_URL", "")
        metrics_queries: dict[str, str] = scenario.get("metrics_queries") or {}
        # Promql-form assertions (see harness/result.py:_evaluate_promql_assertion)
        # each fire their own ad hoc query, in addition to the named metrics_queries
        # above. promql_after_baseline holds each template with ${baseline.x} already
        # resolved (once, right after the baseline fetch below); ${harness.x} is
        # re-resolved every poll tick in _fetch_metrics_once, since those values
        # change continuously during the run.
        promql_templates: dict[str, str] = _collect_promql_assertions(assertions, task_defs)
        # None here means the template's ${baseline.x} reference is declared but came
        # back with no data (see _substitute_baseline_vars) — permanently un-firable
        # for this run, so the assertion just stays PENDING rather than crashing it.
        promql_after_baseline: dict[str, str | None] = dict(promql_templates)
        metrics_enabled = bool(metrics_url and (metrics_queries or promql_templates))

        async def _fetch_metrics_once() -> None:
            if not metrics_enabled:
                return
            resolved_assertion_queries: dict[str, str] = {}
            for name, tmpl in promql_after_baseline.items():
                if tmpl is None:
                    continue
                resolved = _substitute_harness_vars(tmpl, shared_state)
                if resolved is not None:
                    resolved_assertion_queries[name] = resolved
            all_queries = {**metrics_queries, **resolved_assertion_queries}
            if not all_queries:
                return
            try:
                raw = await fetch_metrics(metrics_url, all_queries, sa_token)
            except Exception as exc:
                print(f"[runner] metrics poll error: {exc}", flush=True)
                return
            if not raw:
                return
            baseline = shared_state.get("metrics_baseline") or {}
            deltas = {
                f"{key}_delta": value - baseline[key]
                for key, value in raw.items()
                if key in baseline
            }
            shared_state["metrics"] = {**raw, **deltas}

        async def _settle_and_evaluate(
            assertions_to_check: dict[str, str | dict], max_wait_s: float
        ) -> list[AssertionResult]:
            """Evaluate assertions_to_check, polling MaaS metrics up to max_wait_s and
            re-evaluating after each poll, stopping as soon as every one of them is
            PASSING (or the cap is hit, whichever comes first). Used both right after
            a task with metrics-dependent assertions completes, and for the scenario's
            top-level assertions after cleanup.
            """
            if not metrics_enabled or not assertions_to_check:
                return evaluate_all_assertions(assertions_to_check, shared_state)
            elapsed = 0.0
            while True:
                await _fetch_metrics_once()
                results = evaluate_all_assertions(assertions_to_check, shared_state)
                if all(r.status == "PASSING" for r in results) or elapsed >= max_wait_s:
                    return results
                await asyncio.sleep(_METRICS_FINAL_POLL_INTERVAL_S)
                elapsed += _METRICS_FINAL_POLL_INTERVAL_S

        async def _metrics_bg() -> None:
            while True:
                await _fetch_metrics_once()
                if shared_state.get("metrics"):
                    await emit()
                await asyncio.sleep(5)

        ctx = TaskContext(
            run_id=self.run_id,
            scenario_name=scenario_name,
            maas_api_url=config.get("MAAS_API_URL", ""),
            sa_token=sa_token,
            shared_state=shared_state,
            config=config,
            assertions=assertions,
            emit_assertion_state=emit,
            metrics_queries=metrics_queries,
        )

        tasks: list[Task] = []
        for task_def in task_defs:
            task_class = REGISTRY[task_def["name"]]
            tasks.append(task_class(name=task_def["name"], params=task_def.get("params") or {}))

        task_results: list[TaskResult] = []
        current_task_idx = -1
        run_failed = False
        max_wait_s = _configured_max_wait_s(assertions, task_defs)

        _write_progress(-1, [])
        metrics_bg = None
        if metrics_enabled:
            baseline = await fetch_metrics(metrics_url, metrics_queries, sa_token)
            if baseline:
                shared_state["metrics_baseline"] = baseline
            promql_after_baseline = {
                name: _substitute_baseline_vars(tmpl, baseline or {}, set(metrics_queries))
                for name, tmpl in promql_templates.items()
            }
            metrics_bg = asyncio.create_task(_metrics_bg())

        for i, (task, task_def) in enumerate(zip(tasks, task_defs)):
            current_task_idx = i
            current_task_assertions = task_def.get("assertions") or {}
            _write_progress(i, task_results)
            print(f"[runner] task: {task.name}", flush=True)
            start = time.monotonic()
            try:
                result = await task.run(ctx)
                if current_task_assertions:
                    # Settling can take a while (up to max_wait_s) — leave
                    # shared_state["task_progress"] in place until it's done, so the
                    # UI keeps showing the task's last known progress bar throughout
                    # the wait instead of it vanishing the instant task.run() returns
                    # and only reappearing once the task is finally marked DONE below.
                    task_assertion_results = await _settle_and_evaluate(
                        current_task_assertions, max_wait_s
                    )
                    result.assertions = task_assertion_results
                    if result.status == "PASS" and any(a.status == "FAILING" for a in task_assertion_results):
                        result.status = "FAIL"
                        result.error = "assertions failed at task completion"
                tp = shared_state.pop("task_progress", None)
                if tp:
                    task_completed_progress[task.name] = tp
                task_results.append(result)
                if result.status == "FAIL":
                    run_failed = True
                    break
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                print(
                    f"[runner] task FAILED: {task.name}\n{traceback.format_exc()}",
                    flush=True,
                )
                tp = shared_state.pop("task_progress", None)
                if tp:
                    task_completed_progress[task.name] = tp
                task_results.append(
                    TaskResult(
                        task_name=task.name,
                        status="FAIL",
                        duration_ms=duration_ms,
                        error=str(exc),
                    )
                )
                run_failed = True
                break

        for task in reversed(tasks):
            print(f"[runner] cleanup: {task.name}", flush=True)
            try:
                await task.cleanup(ctx)
            except Exception:
                print(
                    f"[runner] cleanup FAILED: {task.name}\n{traceback.format_exc()}",
                    flush=True,
                )

        # Stop the background metrics poller, then let the scenario's top-level
        # assertions settle the same way per-task ones do (_settle_and_evaluate).
        if metrics_bg:
            metrics_bg.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await metrics_bg

        assertion_results = await _settle_and_evaluate(assertions, max_wait_s)
        # Final (non-debounced) writes so files reflect the definitive end state.
        # current_task_assertions cleared — all task assertions are now frozen in task_results.
        current_task_assertions = {}
        _write_assertions(
            completed_task_results=task_results,
            current_task_name=None,
            current_task_assertion_results=[],
            global_assertion_results=assertion_results,
        )
        _write_progress(len(tasks), task_results)
        status = "FAIL" if run_failed else compute_run_status(task_results, assertion_results)

        return RunResult(
            run_id=self.run_id,
            scenario_name=scenario_name,
            status=status,
            tasks=task_results,
            assertions=assertion_results,
        )
