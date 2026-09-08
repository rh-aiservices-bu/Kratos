import time

import httpx

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY


class ProvisionApiKeyTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        key_name = str(self.params.get("key_name") or f"kratos-{ctx.run_id[:8]}")
        count = int(self.params.get("count", 1))

        async with httpx.AsyncClient() as client:
            for i in range(count):
                name_i = f"{key_name}-{i + 1}" if count > 1 else key_name
                resp = await client.post(
                    f"{ctx.maas_api_url}/maas-api/v1/api-keys",
                    json={"name": name_i},
                    headers={"Authorization": f"Bearer {ctx.sa_token}"},
                )
                resp.raise_for_status()
                data = resp.json()
                ctx.shared_state.setdefault("api_keys", []).append(
                    {"id": data["id"], "key": data["key"]}
                )
                await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        api_keys = ctx.shared_state.get("api_keys", [])
        if not api_keys:
            return
        ids = [k["id"] for k in api_keys]
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{ctx.maas_api_url}/maas-api/v1/api-keys/bulk-revoke",
                    json={"ids": ids},
                    headers={"Authorization": f"Bearer {ctx.sa_token}"},
                )
                resp.raise_for_status()
            except Exception as exc:
                print(f"[provision_api_key] cleanup warning: {exc}", flush=True)


REGISTRY["provision_api_key"] = ProvisionApiKeyTask
