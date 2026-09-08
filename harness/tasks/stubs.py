"""Stub tasks used only for Phase 1 testing. Not for production scenarios."""
import time

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY


class StubPassTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        print(f"[stub_pass] running (run_id={ctx.run_id})", flush=True)
        ctx.shared_state.setdefault("stub_ran", []).append("stub_pass")
        await ctx.emit_assertion_state()
        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        print("[stub_pass] cleanup", flush=True)


class StubFailTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        print(f"[stub_fail] running (run_id={ctx.run_id})", flush=True)
        raise RuntimeError("stub task intentionally failed")

    async def cleanup(self, ctx: TaskContext) -> None:
        print("[stub_fail] cleanup", flush=True)


REGISTRY["stub_pass"] = StubPassTask
REGISTRY["stub_fail"] = StubFailTask
