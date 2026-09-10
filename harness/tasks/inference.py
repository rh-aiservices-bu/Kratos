import asyncio
import time

from openai import AsyncOpenAI

from harness.result import TaskResult
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY

_DEBOUNCE_SECS = 0.1


def _redact(token: str) -> str:
    if not token:
        return "(empty)"
    return token[:8] + "****" if len(token) > 8 else "****"


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

        url, model, token = await self._resolve_url_model_and_token(ctx)
        key_pool = self._resolve_key_pool(ctx)

        if key_pool:
            clients = [AsyncOpenAI(api_key=k, base_url=url) for k in key_pool]
            print(
                f"[send_requests] base_url={url} model={model} "
                f"keys=[{', '.join(_redact(k) for k in key_pool)}] "
                f"count={count} concurrency={concurrency}",
                flush=True,
            )
        else:
            clients = [AsyncOpenAI(api_key=token, base_url=url)]
            print(
                f"[send_requests] base_url={url} model={model} "
                f"token={_redact(token)} count={count} concurrency={concurrency}",
                flush=True,
            )

        latencies: list[float] = []
        success = 0
        fail = 0
        total_tokens_sent = 0
        prompt_tokens_sent = 0
        completion_tokens_sent = 0
        run_start = time.monotonic()
        last_emit = 0.0

        sem = asyncio.Semaphore(concurrency)

        async def do_request(client_idx: int) -> None:
            nonlocal success, fail, last_emit
            nonlocal total_tokens_sent, prompt_tokens_sent, completion_tokens_sent
            async with sem:
                t0 = time.monotonic()
                try:
                    response = await clients[client_idx].chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    success += 1
                    usage = getattr(response, "usage", None)
                    tokens = getattr(usage, "total_tokens", None)
                    if isinstance(tokens, (int, float)):
                        total_tokens_sent += int(tokens)
                    prompt_tokens = getattr(usage, "prompt_tokens", None)
                    if isinstance(prompt_tokens, (int, float)):
                        prompt_tokens_sent += int(prompt_tokens)
                    completion_tokens = getattr(usage, "completion_tokens", None)
                    if isinstance(completion_tokens, (int, float)):
                        completion_tokens_sent += int(completion_tokens)
                except Exception as exc:
                    fail += 1
                    print(f"[send_requests] request failed: {exc}", flush=True)

                latencies.append((time.monotonic() - t0) * 1000)
                total = success + fail
                elapsed = time.monotonic() - run_start
                ctx.shared_state["inference_results"] = {
                    "total_requests": total,
                    "success_count": success,
                    "fail_count": fail,
                    "error_rate_pct": (fail / total * 100) if total > 0 else 0.0,
                    "throughput_rps": success / elapsed if elapsed > 0 else 0.0,
                    "total_tokens_sent": total_tokens_sent,
                    "prompt_tokens_sent": prompt_tokens_sent,
                    "completion_tokens_sent": completion_tokens_sent,
                    **_percentiles(latencies),
                }
                ctx.shared_state["task_progress"] = {"current": total, "total": count}
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

    async def _resolve_url_model_and_token(self, ctx: TaskContext) -> tuple[str, str, str]:
        url = self.params.get("url") or ctx.shared_state.get("url")
        token = self.params.get("token") or ctx.shared_state.get("token") or ctx.sa_token
        default_model = str(
            self.params.get("model")
            or ctx.config.get("target_model")
            or ctx.config.get("DEFAULT_MODEL", "granite-3-8b-instruct")
        )
        if url:
            return str(url), default_model, str(token)
        base_url, resolved_model = await self._discover_model(ctx, default_model)
        return base_url, resolved_model, str(token)

    async def _discover_model(self, ctx: TaskContext, want: str) -> tuple[str, str]:
        """Return (base_url, model_id) by querying /v1/models.

        Matches want against m['id'] or m['modelDetails']['displayName'].
        Falls through to first available if no match.
        The returned model_id is always the canonical m['id'] from the discovery
        response, not the want string — ensures the inference call uses the ID
        the endpoint actually recognises.
        """
        import httpx

        discovery_url = f"{ctx.maas_api_url}/v1/models"
        print(
            f"[send_requests] GET {discovery_url} (token={_redact(ctx.sa_token)})",
            flush=True,
        )
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                discovery_url,
                headers={"Authorization": f"Bearer {ctx.sa_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        print(f"[send_requests] discovery response: {data}", flush=True)

        def _base(url: str) -> str:
            b = url.rstrip("/")
            return b if b.endswith("/v1") else f"{b}/v1"

        for m in data.get("data", []):
            display = (m.get("modelDetails") or {}).get("displayName", "")
            if m["id"] == want or display == want:
                base = _base(m["url"])
                print(
                    f"[send_requests] matched model id={m['id']} display={display!r} "
                    f"base_url={base}",
                    flush=True,
                )
                return base, m["id"]

        if data.get("data"):
            first = data["data"][0]
            base = _base(first["url"])
            print(
                f"[send_requests] {want!r} not matched; using first available "
                f"id={first['id']} base_url={base}",
                flush=True,
            )
            return base, first["id"]

        fallback = f"{ctx.maas_api_url}/v1"
        print(
            f"[send_requests] no models in discovery response; falling back to {fallback} model={want}",
            flush=True,
        )
        return fallback, want

    def _resolve_key_pool(self, ctx: TaskContext) -> list[str]:
        if not self.params.get("key_pool"):
            return []
        return [k["key"] for k in ctx.shared_state.get("api_keys", [])]

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["send_requests"] = SendRequestsTask
