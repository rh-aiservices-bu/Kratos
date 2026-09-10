import asyncio
import contextlib
import json
import os
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
from harness.metrics_client import fetch_metrics, parse_queries
from harness.result import (
    RunResult,
    TaskResult,
    compute_run_status,
    evaluate_all_assertions,
)
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_EMIT_DEBOUNCE_S = 0.1
_METRICS_FINAL_MAX_WAIT_S = 40.0
_METRICS_FINAL_POLL_INTERVAL_S = 5.0


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
        metrics_queries: dict[str, str] = parse_queries(config.get("MAAS_METRICS_QUERIES", ""))
        metrics_enabled = bool(metrics_url and metrics_queries)

        async def _fetch_metrics_once() -> None:
            if not metrics_enabled:
                return
            try:
                raw = await fetch_metrics(metrics_url, metrics_queries, sa_token)
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
        )

        tasks: list[Task] = []
        for task_def in task_defs:
            task_class = REGISTRY[task_def["name"]]
            tasks.append(task_class(name=task_def["name"], params=task_def.get("params") or {}))

        task_results: list[TaskResult] = []
        current_task_idx = -1
        run_failed = False

        _write_progress(-1, [])
        metrics_bg = None
        if metrics_enabled:
            baseline = await fetch_metrics(metrics_url, metrics_queries, sa_token)
            if baseline:
                shared_state["metrics_baseline"] = baseline
            metrics_bg = asyncio.create_task(_metrics_bg())

        for i, (task, task_def) in enumerate(zip(tasks, task_defs)):
            current_task_idx = i
            current_task_assertions = task_def.get("assertions") or {}
            _write_progress(i, task_results)
            print(f"[runner] task: {task.name}", flush=True)
            start = time.monotonic()
            try:
                result = await task.run(ctx)
                tp = shared_state.pop("task_progress", None)
                if tp:
                    task_completed_progress[task.name] = tp
                if current_task_assertions:
                    await _fetch_metrics_once()
                    task_assertion_results = evaluate_all_assertions(current_task_assertions, shared_state)
                    result.assertions = task_assertion_results
                    if result.status == "PASS" and any(a.status == "FAILING" for a in task_assertion_results):
                        result.status = "FAIL"
                        result.error = "assertions failed at task completion"
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

        # Stop background metrics poller, then fetch a definitive final state. A single
        # fetch immediately after cleanup can land inside the same Prometheus scrape
        # interval the run started in — for a scenario that finishes faster than the
        # scrape interval (commonly ~30s), that reads back as an unchanged baseline
        # (delta=0) even though the traffic really happened, which a tolerance-band
        # comparison can't distinguish from "genuinely nothing changed". So retry a
        # few times, stopping as soon as any metric has moved past its baseline
        # (evidence a fresh scrape has landed) or a bounded cap is hit.
        if metrics_bg:
            metrics_bg.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await metrics_bg
            baseline = shared_state.get("metrics_baseline") or {}
            elapsed = 0.0
            while elapsed < _METRICS_FINAL_MAX_WAIT_S:
                await _fetch_metrics_once()
                current = {
                    k: v for k, v in shared_state.get("metrics", {}).items() if not k.endswith("_delta")
                }
                if any(current.get(k) != baseline.get(k) for k in current):
                    break
                await asyncio.sleep(_METRICS_FINAL_POLL_INTERVAL_S)
                elapsed += _METRICS_FINAL_POLL_INTERVAL_S

        assertion_results = evaluate_all_assertions(assertions, shared_state)
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
