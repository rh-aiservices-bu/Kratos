import json
import time
import traceback
from pathlib import Path

_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


def _read_sa_token(config: dict) -> str:
    if token := config.get("SA_TOKEN", ""):
        return token
    try:
        return Path(_SA_TOKEN_PATH).read_text().strip()
    except OSError:
        return ""

from harness.config import load_scenario
from harness.result import (
    RunResult,
    TaskResult,
    compute_run_status,
    evaluate_all_assertions,
)
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_EMIT_DEBOUNCE_S = 0.1


class ScenarioRunner:
    def __init__(self, scenario_path: str, run_id: str) -> None:
        self.scenario_path = scenario_path
        self.run_id = run_id
        self._last_emit: float = 0.0

    async def run(self) -> RunResult:
        scenario = load_scenario(self.scenario_path)
        scenario_name: str = scenario["name"]
        config: dict = scenario.get("_resolved_config", {})
        assertions: dict[str, str] = scenario.get("assertions") or {}
        task_defs: list[dict] = scenario.get("tasks") or []
        shared_state: dict = {}

        async def emit() -> None:
            now = time.monotonic()
            if now - self._last_emit < _EMIT_DEBOUNCE_S:
                return
            self._last_emit = now
            results = evaluate_all_assertions(assertions, shared_state)
            payload = {
                "event": "assertion_state",
                "data": [
                    {"name": r.name, "status": r.status, "value": r.current_value}
                    for r in results
                ],
            }
            print(f"data: {json.dumps(payload)}", flush=True)

        ctx = TaskContext(
            run_id=self.run_id,
            scenario_name=scenario_name,
            maas_api_url=config.get("MAAS_API_URL", ""),
            sa_token=_read_sa_token(config),
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
        run_failed = False

        for task in tasks:
            print(f"[runner] task: {task.name}", flush=True)
            start = time.monotonic()
            try:
                result = await task.run(ctx)
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

        assertion_results = evaluate_all_assertions(assertions, shared_state)
        status = "FAIL" if run_failed else compute_run_status(task_results, assertion_results)

        return RunResult(
            run_id=self.run_id,
            scenario_name=scenario_name,
            status=status,
            tasks=task_results,
            assertions=assertion_results,
        )
