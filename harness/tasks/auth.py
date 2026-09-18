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


async def _revoke_keys(ctx: TaskContext) -> int:
    """DELETE every key in shared_state["api_keys"] via the MaaS REST API.

    Shared by ProvisionApiKeyTask.cleanup() (end of scenario, as before) and
    RevokeApiKeysTask.run() (mid-scenario — lets a later task confirm
    inference is denied immediately, not after some caching delay; see
    scenarios/api_key_lifecycle.yaml and ADR-019). Returns how many DELETEs
    succeeded; a key already gone (e.g. revoked earlier in the same run) just
    fails its own DELETE, logged and swallowed like any other cleanup error —
    not a new failure mode.
    """
    api_keys = ctx.shared_state.get("api_keys", [])
    if not api_keys:
        return 0

    revoked = 0
    async with httpx.AsyncClient() as client:
        for key in api_keys:
            key_id = key["id"]
            del_url = f"{ctx.maas_api_url}/maas-api/v1/api-keys/{key_id}"
            print(f"[revoke_keys] DELETE {del_url} (token={_redact(ctx.sa_token)})", flush=True)
            try:
                resp = await client.delete(
                    del_url,
                    headers={"Authorization": f"Bearer {ctx.sa_token}"},
                )
                if not resp.is_success:
                    print(
                        f"[revoke_keys] DELETE {del_url} → {resp.status_code}: {resp.text}",
                        flush=True,
                    )
                resp.raise_for_status()
                revoked += 1
                print(f"[revoke_keys] deleted key {key_id}", flush=True)
            except Exception:
                print(
                    f"[revoke_keys] DELETE {key_id} FAILED\n{traceback.format_exc()}",
                    flush=True,
                )
    return revoked


class ProvisionApiKeyTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        key_name = str(self.params.get("key_name") or f"kratos-{ctx.run_id[:8]}")
        count = int(self.params.get("count", 1))
        # Explicit subscription binding — without it, key creation
        # auto-selects whichever subscription the caller's identity resolves
        # to (highest priority among eligible ones), which may not be the
        # subscription a scenario is specifically trying to validate (e.g.
        # rate_limit_validation's test CR). Passing this pins the created
        # keys to a known subscription regardless of what else the caller is
        # eligible for.
        subscription = self.params.get("subscription")

        # REST-only lifecycle checks (ADR-019, empirical-verification-checklist.md):
        # does the create response actually echo what we asked for, rather
        # than us trusting it silently? Pure request-vs-response comparison —
        # no CR read involved, so this holds up across MaaS schema changes.
        # subscription_checked_count is its own counter (not just total_keys)
        # because a scenario may not pass `subscription` at all.
        checks = ctx.shared_state.setdefault(
            "key_provision_checks",
            {
                "total_keys": 0,
                "name_echo_match_count": 0,
                "subscription_checked_count": 0,
                "subscription_echo_match_count": 0,
                "expires_at_present_count": 0,
            },
        )

        url = f"{ctx.maas_api_url}/maas-api/v1/api-keys"
        async with httpx.AsyncClient() as client:
            for i in range(count):
                name_i = f"{key_name}-{i + 1}" if count > 1 else key_name
                body: dict = {"name": name_i}
                if subscription:
                    body["subscription"] = subscription
                print(
                    f"[provision_api_key] POST {url} "
                    f"body={body!r} "
                    f"(token={_redact(ctx.sa_token)})",
                    flush=True,
                )
                resp = await client.post(
                    url,
                    json=body,
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
                    {
                        "id": data["id"],
                        "key": data["key"],
                        "name": data.get("name"),
                        "subscription": data.get("subscription"),
                        "expiresAt": data.get("expiresAt"),
                    }
                )

                checks["total_keys"] += 1
                if data.get("name") == name_i:
                    checks["name_echo_match_count"] += 1
                if subscription:
                    checks["subscription_checked_count"] += 1
                    if data.get("subscription") == subscription:
                        checks["subscription_echo_match_count"] += 1
                if data.get("expiresAt"):
                    checks["expires_at_present_count"] += 1

                ctx.shared_state["task_progress"] = {"current": i + 1, "total": count}
                await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        await _revoke_keys(ctx)


class RevokeApiKeysTask(Task):
    """Revoke every currently-provisioned API key mid-scenario, not at
    cleanup time — lets a later `send_requests`-family task confirm
    inference is denied right away. See scenarios/api_key_lifecycle.yaml
    and ADR-019. Reuses the same DELETE loop as ProvisionApiKeyTask's own
    cleanup(); that cleanup still runs at the end of the scenario and will
    harmlessly re-attempt DELETE on these already-gone keys.
    """

    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        revoked = await _revoke_keys(ctx)
        ctx.shared_state["revoked_count"] = revoked
        await ctx.emit_assertion_state()
        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


class VerifyApiKeySearchTask(Task):
    """Confirm POST /maas-api/v1/api-keys/search actually finds the keys
    this run created, filtered by name_prefix — REST-only, no CR read.

    Honest scope limit: with only the harness's own SA identity available,
    this proves inclusion (our keys are findable) and filtering (name_prefix
    narrows correctly), not true caller-scoping (that a *different* caller's
    keys are excluded) — see the open caveat in
    docs/architecture/empirical-verification-checklist.md.
    """

    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()
        name_prefix = str(self.params.get("name_prefix", ""))
        url = f"{ctx.maas_api_url}/maas-api/v1/api-keys/search"
        body: dict = {"name_prefix": name_prefix} if name_prefix else {}
        print(f"[verify_api_key_search] POST {url} body={body!r}", flush=True)

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {ctx.sa_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        found = data.get("items", [])
        found_count = len(found)
        expected_count = len(ctx.shared_state.get("api_keys", []))
        ctx.shared_state["search_check"] = {
            "found_count": found_count,
            "expected_count": expected_count,
        }
        print(
            f"[verify_api_key_search] found={found_count} expected={expected_count}",
            flush=True,
        )
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["provision_api_key"] = ProvisionApiKeyTask
REGISTRY["revoke_api_keys"] = RevokeApiKeysTask
REGISTRY["verify_api_key_search"] = VerifyApiKeySearchTask
