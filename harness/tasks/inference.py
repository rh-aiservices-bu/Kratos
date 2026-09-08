import asyncio
import time

from openai import AsyncOpenAI

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_DEBOUNCE_SECS = 0.1


def _distribute(total: int, n_keys: int) -> list[int]:
    """Return per-key request counts: floor(total/n_keys) each, remainder to first."""
    base = total // n_keys
    remainder = total % n_keys
    return [base + (remainder if i == 0 else 0) for i in range(n_keys)]


def _percentiles(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0, "p99_latency_ms": 0.0}
    s = sorted(latencies)
    n = len(s)

    def _pct(p: float) -> float:
        return s[min(int(n * p / 100), n - 1)]

    return {
        "p50_latency_ms": _pct(50),
        "p95_latency_ms": _pct(95),
        "p99_latency_ms": _pct(99),
    }


class SendRequestsTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        count = int(self.params.get("count", 10))
        concurrency = int(self.params.get("concurrency", 5))
        prompt = str(self.params.get("prompt", "Hello"))
        model = str(
            self.params.get("model") or ctx.config.get("DEFAULT_MODEL", "granite-3-8b-instruct")
        )

        url, token = await self._resolve_url_and_token(ctx)
        key_pool = self._resolve_key_pool(ctx)

        if key_pool:
            clients = [AsyncOpenAI(api_key=k, base_url=url) for k in key_pool]
        else:
            clients = [AsyncOpenAI(api_key=token, base_url=url)]

        latencies: list[float] = []
        success = 0
        fail = 0
        run_start = time.monotonic()
        last_emit = 0.0

        sem = asyncio.Semaphore(concurrency)

        async def do_request(client_idx: int) -> None:
            nonlocal success, fail, last_emit
            async with sem:
                t0 = time.monotonic()
                try:
                    await clients[client_idx].chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    success += 1
                except Exception:
                    fail += 1

                latencies.append((time.monotonic() - t0) * 1000)
                total = success + fail
                elapsed = time.monotonic() - run_start
                ctx.shared_state["inference_results"] = {
                    "total_requests": total,
                    "success_count": success,
                    "fail_count": fail,
                    "error_rate_pct": (fail / total * 100) if total > 0 else 0.0,
                    "throughput_rps": success / elapsed if elapsed > 0 else 0.0,
                    **_percentiles(latencies),
                }
                now = time.monotonic()
                if now - last_emit >= _DEBOUNCE_SECS:
                    last_emit = now
                    await ctx.emit_assertion_state()

        if key_pool:
            assignments = _distribute(count, len(key_pool))
            request_tasks = []
            for key_idx, n_reqs in enumerate(assignments):
                for _ in range(n_reqs):
                    request_tasks.append(do_request(key_idx))
        else:
            request_tasks = [do_request(0) for _ in range(count)]

        await asyncio.gather(*request_tasks)
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _resolve_url_and_token(self, ctx: TaskContext) -> tuple[str, str]:
        url = self.params.get("url") or ctx.shared_state.get("url")
        token = self.params.get("token") or ctx.shared_state.get("token") or ctx.sa_token
        if not url:
            url = await self._discover_model_url(ctx)
        return str(url), str(token)

    async def _discover_model_url(self, ctx: TaskContext) -> str:
        import httpx

        model = str(
            self.params.get("model") or ctx.config.get("DEFAULT_MODEL", "granite-3-8b-instruct")
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{ctx.maas_api_url}/v1/models",
                headers={"Authorization": f"Bearer {ctx.sa_token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        for m in data.get("data", []):
            if m["id"] == model:
                return f"{m['url']}/v1/chat/completions"
        if data.get("data"):
            return f"{data['data'][0]['url']}/v1/chat/completions"
        return f"{ctx.maas_api_url}/v1/chat/completions"

    def _resolve_key_pool(self, ctx: TaskContext) -> list[str]:
        if not self.params.get("key_pool"):
            return []
        return [k["key"] for k in ctx.shared_state.get("api_keys", [])]

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["send_requests"] = SendRequestsTask
