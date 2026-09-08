import time
import traceback

import httpx

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY


def _redact(token: str) -> str:
    if not token:
        return "(empty)"
    return token[:8] + "****" if len(token) > 8 else "****"


class ProvisionApiKeyTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        key_name = str(self.params.get("key_name") or f"kratos-{ctx.run_id[:8]}")
        count = int(self.params.get("count", 1))

        url = f"{ctx.maas_api_url}/maas-api/v1/api-keys"
        async with httpx.AsyncClient() as client:
            for i in range(count):
                name_i = f"{key_name}-{i + 1}" if count > 1 else key_name
                print(
                    f"[provision_api_key] POST {url} "
                    f"body={{name: {name_i!r}}} "
                    f"(token={_redact(ctx.sa_token)})",
                    flush=True,
                )
                resp = await client.post(
                    url,
                    json={"name": name_i},
                    headers={"Authorization": f"Bearer {ctx.sa_token}"},
                )
                if not resp.is_success:
                    print(
                        f"[provision_api_key] POST {url} → {resp.status_code}: {resp.text}",
                        flush=True,
                    )
                resp.raise_for_status()
                data = resp.json()
                print(
                    f"[provision_api_key] created key id={data.get('id')} name={data.get('name')}",
                    flush=True,
                )
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

        # bulk-revoke requires a Username field we don't have; individual DELETE works fine.
        async with httpx.AsyncClient() as client:
            for key in api_keys:
                key_id = key["id"]
                del_url = f"{ctx.maas_api_url}/maas-api/v1/api-keys/{key_id}"
                print(
                    f"[provision_api_key] DELETE {del_url} (token={_redact(ctx.sa_token)})",
                    flush=True,
                )
                try:
                    resp = await client.delete(
                        del_url,
                        headers={"Authorization": f"Bearer {ctx.sa_token}"},
                    )
                    if not resp.is_success:
                        print(
                            f"[provision_api_key] DELETE {del_url} → {resp.status_code}: {resp.text}",
                            flush=True,
                        )
                    resp.raise_for_status()
                    print(f"[provision_api_key] deleted key {key_id}", flush=True)
                except Exception:
                    print(
                        f"[provision_api_key] DELETE {key_id} FAILED\n{traceback.format_exc()}",
                        flush=True,
                    )


REGISTRY["provision_api_key"] = ProvisionApiKeyTask
