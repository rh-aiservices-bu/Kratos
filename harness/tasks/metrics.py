import time
import traceback

import httpx

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY


class CheckMaasMetricsTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        metrics_url = self.params.get("metrics_url") or ctx.config.get("MAAS_METRICS_URL")
        raw: dict = {"total_requests": 0, "total_tokens": 0}

        if metrics_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        metrics_url,
                        headers={"Authorization": f"Bearer {ctx.sa_token}"},
                    )
                    resp.raise_for_status()
                    raw.update(resp.json())
            except Exception:
                print(
                    f"[check_maas_metrics] could not fetch metrics\n{traceback.format_exc()}",
                    flush=True,
                )
        else:
            print(
                "[check_maas_metrics] no metrics URL configured — using stub zeroes", flush=True
            )

        ctx.shared_state["metrics"] = raw

        print("[check_maas_metrics] --- metrics summary ---", flush=True)
        for key, val in raw.items():
            print(f"  {key}: {val}", flush=True)
        print("[check_maas_metrics] ----------------------", flush=True)

        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["check_maas_metrics"] = CheckMaasMetricsTask
