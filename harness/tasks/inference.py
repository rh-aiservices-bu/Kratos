import asyncio
import json
import os
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


async def _resolve_endpoint(params: dict, ctx: TaskContext) -> tuple[str, str, str]:
    """Resolve (base_url, model_id, token) for inference via 3-level priority chain."""
    url = params.get("url") or ctx.shared_state.get("url")
    token = params.get("token") or ctx.shared_state.get("token") or ctx.sa_token
    default_model = str(
        params.get("model") or ctx.config.get("DEFAULT_MODEL", "granite-3-8b-instruct")
    )
    if url:
        return str(url), default_model, str(token)
    base_url, resolved_model = await _discover_model(ctx, default_model)
    return base_url, resolved_model, str(token)


async def _discover_model(ctx: TaskContext, want: str) -> tuple[str, str]:
    """Return (base_url, model_id) by querying /v1/models."""
    import httpx

    discovery_url = f"{ctx.maas_api_url}/v1/models"
    print(f"[inference] GET {discovery_url} (token={_redact(ctx.sa_token)})", flush=True)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            discovery_url,
            headers={"Authorization": f"Bearer {ctx.sa_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    print(f"[inference] discovery response: {data}", flush=True)

    def _base(url: str) -> str:
        b = url.rstrip("/")
        return b if b.endswith("/v1") else f"{b}/v1"

    for m in data.get("data", []):
        display = (m.get("modelDetails") or {}).get("displayName", "")
        if m["id"] == want or display == want:
            base = _base(m["url"])
            print(
                f"[inference] matched model id={m['id']} display={display!r} base_url={base}",
                flush=True,
            )
            return base, m["id"]

    if data.get("data"):
        first = data["data"][0]
        base = _base(first["url"])
        print(
            f"[inference] {want!r} not matched; using first available id={first['id']} base_url={base}",
            flush=True,
        )
        return base, first["id"]

    fallback = f"{ctx.maas_api_url}/v1"
    print(
        f"[inference] no models in discovery response; falling back to {fallback} model={want}",
        flush=True,
    )
    return fallback, want


def _resolve_key_pool(params: dict, ctx: TaskContext) -> list[str]:
    if not params.get("key_pool"):
        return []
    return [k["key"] for k in ctx.shared_state.get("api_keys", [])]


def _instance_seed(run_id: str, idx: int) -> int:
    return abs(hash(f"{run_id}:{idx}")) % (2**31)


def _write_prompt_file(prompt: str, tag: str) -> str:
    path = f"/tmp/guidellm-prompt-{tag}.txt"
    with open(path, "w") as f:
        f.write(prompt)
    return path


def _empty_instance_result() -> dict:
    return {
        "total": 0,
        "success": 0,
        "fail": 0,
        "throughput_rps": 0.0,
        "p50_latency_ms": 0.0,
        "p95_latency_ms": 0.0,
        "p99_latency_ms": 0.0,
        "guidellm": {},
    }


def _parse_guidellm_output(path: str, instance_idx: int) -> dict:
    """Parse a GuideLLM JSON report file and return normalised result dict."""
    try:
        from guidellm.benchmark import GenerativeBenchmarksReport  # type: ignore[import]

        report = GenerativeBenchmarksReport.load_file(path)
        bm = report.benchmarks[0]
        m = bm.metrics

        # request_latency is in seconds; convert to ms
        p50 = m.request_latency.successful.percentiles.p50 * 1000
        p95 = m.request_latency.successful.percentiles.p95 * 1000
        p99 = m.request_latency.successful.percentiles.p99 * 1000
        rps = m.requests_per_second.successful.mean

        # Request counts — try known attribute paths; fall back to JSON if missing
        try:
            success = int(bm.stats.successful_request_count)
            fail = int(bm.stats.error_request_count) + int(bm.stats.incomplete_request_count)
        except AttributeError:
            # Attribute paths may vary by guidellm version; read raw JSON as fallback
            with open(path) as f:
                raw = json.load(f)
            bench_raw = raw.get("benchmarks", [{}])[0]
            stats_raw = bench_raw.get("stats", {})
            success = int(stats_raw.get("successful_request_count", 0))
            fail = int(stats_raw.get("error_request_count", 0)) + int(
                stats_raw.get("incomplete_request_count", 0)
            )

        # Richer guidellm-specific metrics for future assertions
        guidellm_extra: dict = {}
        try:
            guidellm_extra["ttft_p99_ms"] = m.time_to_first_token_ms.successful.percentiles.p99
            guidellm_extra["itl_mean_ms"] = m.inter_token_latency_ms.successful.mean
            guidellm_extra["output_tokens_per_second"] = m.output_tokens_per_second.successful.mean
        except AttributeError:
            pass

        return {
            "total": success + fail,
            "success": success,
            "fail": fail,
            "throughput_rps": rps,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99,
            "guidellm": guidellm_extra,
        }

    except Exception as exc:
        print(f"[guidellm_benchmark] instance={instance_idx} failed to parse output: {exc}", flush=True)
        return _empty_instance_result()


def _merge_instance_results(results: list[dict]) -> dict:
    """Merge results from multiple GuideLLM instances into shared_state-compatible dicts."""
    total = sum(r["total"] for r in results)
    success = sum(r["success"] for r in results)
    fail = sum(r["fail"] for r in results)

    # Weight throughput by instance count (simple average across instances)
    n = len(results) or 1
    throughput = sum(r["throughput_rps"] for r in results) / n

    # Use max of per-instance tail latencies (conservative across parallel instances)
    p50 = max((r["p50_latency_ms"] for r in results), default=0.0)
    p95 = max((r["p95_latency_ms"] for r in results), default=0.0)
    p99 = max((r["p99_latency_ms"] for r in results), default=0.0)

    inference_results = {
        "total_requests": total,
        "success_count": success,
        "fail_count": fail,
        "error_rate_pct": (fail / total * 100) if total > 0 else 0.0,
        "throughput_rps": throughput,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "p99_latency_ms": p99,
    }

    guidellm_results = {
        "instances": len(results),
        "per_instance": [r["guidellm"] for r in results],
    }

    return {"inference_results": inference_results, "guidellm_results": guidellm_results}


class SendRequestsTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        count = int(self.params.get("count", 10))
        concurrency = int(self.params.get("concurrency", 5))
        prompt = str(self.params.get("prompt", "Hello"))

        url, model, token = await _resolve_endpoint(self.params, ctx)
        key_pool = _resolve_key_pool(self.params, ctx)

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

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


class GuideLLMBenchmarkTask(Task):
    async def run(self, ctx: TaskContext) -> TaskResult:
        start = time.monotonic()

        count = int(self.params.get("count", 10))
        concurrency = int(self.params.get("concurrency", 5))
        prompt = str(self.params.get("prompt", "Hello"))
        prompt_tokens = self.params.get("prompt_tokens")
        output_tokens = self.params.get("output_tokens")
        data_source = str(self.params.get("data_source", "shared"))

        url, model, token = await _resolve_endpoint(self.params, ctx)
        key_pool = _resolve_key_pool(self.params, ctx)

        # Pre-generate a shared data file when all instances should use the same data
        shared_data_file: str | None = None
        if data_source == "shared" and not prompt_tokens:
            shared_data_file = _write_prompt_file(prompt, ctx.run_id)

        try:
            if key_pool:
                print(
                    f"[guidellm_benchmark] launching {len(key_pool)} instances "
                    f"(one per key) url={url} model={model} count={count} concurrency={concurrency}",
                    flush=True,
                )
                coros = [
                    self._run_instance(
                        ctx=ctx,
                        url=url,
                        model=model,
                        api_key=key,
                        count=count,
                        concurrency=concurrency,
                        prompt=prompt,
                        prompt_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        shared_data_file=shared_data_file,
                        data_source=data_source,
                        instance_idx=idx,
                    )
                    for idx, key in enumerate(key_pool)
                ]
                results = list(await asyncio.gather(*coros))
            else:
                print(
                    f"[guidellm_benchmark] url={url} model={model} "
                    f"token={_redact(token)} count={count} concurrency={concurrency}",
                    flush=True,
                )
                results = [
                    await self._run_instance(
                        ctx=ctx,
                        url=url,
                        model=model,
                        api_key=token,
                        count=count,
                        concurrency=concurrency,
                        prompt=prompt,
                        prompt_tokens=prompt_tokens,
                        output_tokens=output_tokens,
                        shared_data_file=shared_data_file,
                        data_source=data_source,
                        instance_idx=0,
                    )
                ]
        finally:
            if shared_data_file and os.path.exists(shared_data_file):
                os.unlink(shared_data_file)

        merged = _merge_instance_results(results)
        ctx.shared_state["inference_results"] = merged["inference_results"]
        ctx.shared_state["guidellm_results"] = merged["guidellm_results"]
        await ctx.emit_assertion_state()

        return TaskResult(
            task_name=self.name,
            status="PASS",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _run_instance(
        self,
        *,
        ctx: TaskContext,
        url: str,
        model: str,
        api_key: str,
        count: int,
        concurrency: int,
        prompt: str,
        prompt_tokens: object,
        output_tokens: object,
        shared_data_file: str | None,
        data_source: str,
        instance_idx: int,
    ) -> dict:
        output_path = f"/tmp/guidellm-{ctx.run_id}-{instance_idx}.json"
        instance_data_file: str | None = None

        try:
            backend = (
                f"kind=openai_http,target={url},api_key={api_key}"
                f",model={model},request_format=/v1/chat/completions,validate_backend=false"
            )

            seed_args: list[str] = []
            if prompt_tokens:
                data = f"kind=synthetic_text,prompt_tokens={prompt_tokens}"
                if output_tokens:
                    data += f",output_tokens={output_tokens}"
                if data_source == "independent":
                    seed_args = ["--seed", f"kind=static,value={_instance_seed(ctx.run_id, instance_idx)}"]
                else:
                    seed_args = ["--seed", f"kind=static,value={_instance_seed(ctx.run_id, 0)}"]
            elif shared_data_file:
                data = f"kind=text_file,path={shared_data_file}"
            else:
                # Independent text mode: write per-instance prompt file
                instance_data_file = _write_prompt_file(prompt, f"{ctx.run_id}-{instance_idx}")
                data = f"kind=text_file,path={instance_data_file}"

            cmd = [
                "guidellm", "run",
                "--backend", backend,
                "--data", data,
                "--profile", f"kind=concurrent,streams={concurrency}",
                "--constraint", f"kind=max_requests,count={count}",
                "--output", f"kind=json,path={output_path}",
                *seed_args,
            ]

            print(
                f"[guidellm_benchmark:{instance_idx}] {' '.join(cmd)}",
                flush=True,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert proc.stdout is not None
            async for line in proc.stdout:
                print(f"[guidellm:{instance_idx}] {line.decode().rstrip()}", flush=True)

            await proc.wait()

            if proc.returncode != 0:
                print(
                    f"[guidellm_benchmark] instance={instance_idx} exited with code {proc.returncode}",
                    flush=True,
                )
                return _empty_instance_result()

            return _parse_guidellm_output(output_path, instance_idx)

        finally:
            for path in filter(None, [output_path, instance_data_file]):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass

    async def cleanup(self, ctx: TaskContext) -> None:
        pass


REGISTRY["send_requests"] = SendRequestsTask
REGISTRY["guidellm_benchmark"] = GuideLLMBenchmarkTask
