import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from harness.tasks.base import TaskContext
from harness.tasks.inference import SendRequestsTask, _distribute, _percentiles


def _make_ctx(shared_state: dict | None = None) -> TaskContext:
    async def _emit() -> None:
        pass

    return TaskContext(
        run_id="test-001",
        scenario_name="test",
        maas_api_url="http://maas.test",
        sa_token="test-token",
        shared_state=shared_state or {},
        config={},
        assertions={},
        emit_assertion_state=_emit,
    )


def _mock_client(*, fail: bool = False) -> MagicMock:
    m = MagicMock()
    if fail:
        m.chat.completions.create = AsyncMock(side_effect=Exception("request failed"))
    else:
        m.chat.completions.create = AsyncMock(return_value=MagicMock())
    return m


async def test_send_requests_updates_inference_results() -> None:
    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client()

        task = SendRequestsTask(
            "send_requests",
            {"count": "3", "concurrency": "2", "prompt": "Hi", "url": "http://m.test", "token": "sk-t"},
        )
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    ir = ctx.shared_state["inference_results"]
    assert ir["total_requests"] == 3
    assert ir["success_count"] == 3
    assert ir["fail_count"] == 0
    assert ir["error_rate_pct"] == 0.0


async def test_send_requests_counts_errors() -> None:
    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client(fail=True)

        task = SendRequestsTask(
            "send_requests",
            {"count": "4", "concurrency": "2", "url": "http://m.test", "token": "sk-t"},
        )
        ctx = _make_ctx()
        result = await task.run(ctx)

    assert result.status == "PASS"
    ir = ctx.shared_state["inference_results"]
    assert ir["fail_count"] == 4
    assert ir["error_rate_pct"] == 100.0


async def test_send_requests_debounce() -> None:
    """Debounce: emit_assertion_state fires at most once per 100 ms burst."""
    emit_times: list[float] = []

    async def _track_emit() -> None:
        emit_times.append(time.monotonic())

    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client()

        task = SendRequestsTask(
            "send_requests",
            {"count": "10", "concurrency": "10", "url": "http://m.test", "token": "sk-t"},
        )
        ctx = TaskContext(
            run_id="test-001",
            scenario_name="test",
            maas_api_url="http://maas.test",
            sa_token="test-token",
            shared_state={},
            config={},
            assertions={},
            emit_assertion_state=_track_emit,
        )
        await task.run(ctx)

    # 10 rapid requests + 1 final emit; debounce must keep total well below 10
    assert len(emit_times) >= 1
    assert len(emit_times) < 10, f"debounce failed: {len(emit_times)} emits for 10 rapid requests"


async def test_key_pool_distribution() -> None:
    """Key-pool distribution: requests spread floor(M/N) each, remainder to first."""
    calls_by_key: dict[str, int] = {}

    def _make_tracking_client(api_key: str | None = None, base_url: str | None = None) -> MagicMock:
        m = MagicMock()

        async def _complete(*args, **kwargs) -> MagicMock:
            calls_by_key[api_key] = calls_by_key.get(api_key, 0) + 1
            return MagicMock()

        m.chat.completions.create = _complete
        return m

    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.side_effect = _make_tracking_client

        ctx = _make_ctx(
            {
                "api_keys": [
                    {"id": "id-1", "key": "sk-key-1"},
                    {"id": "id-2", "key": "sk-key-2"},
                    {"id": "id-3", "key": "sk-key-3"},
                ]
            }
        )
        task = SendRequestsTask(
            "send_requests",
            {
                "count": "6",
                "concurrency": "6",
                "url": "http://m.test",
                "token": "sk-default",
                "key_pool": True,
            },
        )
        await task.run(ctx)

    # 6 requests / 3 keys = 2 each (no remainder)
    assert sum(calls_by_key.values()) == 6
    assert all(v == 2 for v in calls_by_key.values()), f"uneven distribution: {calls_by_key}"


async def test_key_pool_distribution_with_remainder() -> None:
    """Key-pool distribution: remainder goes to first key."""
    calls_by_key: dict[str, int] = {}

    def _make_tracking_client(api_key: str | None = None, base_url: str | None = None) -> MagicMock:
        m = MagicMock()

        async def _complete(*args, **kwargs) -> MagicMock:
            calls_by_key[api_key] = calls_by_key.get(api_key, 0) + 1
            return MagicMock()

        m.chat.completions.create = _complete
        return m

    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.side_effect = _make_tracking_client

        ctx = _make_ctx(
            {
                "api_keys": [
                    {"id": "id-1", "key": "sk-key-1"},
                    {"id": "id-2", "key": "sk-key-2"},
                ]
            }
        )
        task = SendRequestsTask(
            "send_requests",
            {
                "count": "7",
                "concurrency": "7",
                "url": "http://m.test",
                "token": "sk-default",
                "key_pool": True,
            },
        )
        await task.run(ctx)

    # 7 requests / 2 keys: first gets 4 (3+1 remainder), second gets 3
    assert calls_by_key.get("sk-key-1") == 4
    assert calls_by_key.get("sk-key-2") == 3


async def test_url_resolution_explicit_params_priority() -> None:
    """Explicit params override shared_state for url/token."""
    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client()

        task = SendRequestsTask(
            "send_requests",
            {"count": "1", "url": "http://explicit.test", "token": "sk-explicit"},
        )
        ctx = _make_ctx({"url": "http://shared.test", "token": "sk-shared"})
        await task.run(ctx)

    mock_cls.assert_called_with(api_key="sk-explicit", base_url="http://explicit.test")


async def test_url_resolution_shared_state_fallback() -> None:
    """shared_state used when explicit params are absent."""
    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client()

        task = SendRequestsTask("send_requests", {"count": "1"})
        ctx = _make_ctx({"url": "http://shared.test", "token": "sk-shared"})
        await task.run(ctx)

    mock_cls.assert_called_with(api_key="sk-shared", base_url="http://shared.test")


async def test_url_resolution_sa_token_fallback(httpx_mock) -> None:
    """SA token used when no explicit token and no shared_state token."""
    httpx_mock.add_response(
        url="http://maas.test/v1/models",
        json={"data": [{"id": "granite", "url": "http://model.test"}]},
    )

    with patch("harness.tasks.inference.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = _mock_client()

        task = SendRequestsTask("send_requests", {"count": "1"})
        ctx = _make_ctx()  # no url or token in shared_state
        await task.run(ctx)

    mock_cls.assert_called_with(
        api_key="test-token", base_url="http://model.test/v1/chat/completions"
    )


def test_distribute_evenly() -> None:
    assert _distribute(6, 3) == [2, 2, 2]
    assert _distribute(5, 5) == [1, 1, 1, 1, 1]


def test_distribute_with_remainder() -> None:
    """Remainder assigned to first key."""
    assert _distribute(7, 3) == [3, 2, 2]
    assert _distribute(10, 3) == [4, 3, 3]


def test_percentiles_empty() -> None:
    result = _percentiles([])
    assert result["p50_latency_ms"] == 0.0
    assert result["p95_latency_ms"] == 0.0
    assert result["p99_latency_ms"] == 0.0


def test_percentiles_computed() -> None:
    lats = list(range(1, 101))  # 1 to 100, sorted; n=100
    result = _percentiles(lats)
    # floor-index: int(100*p/100) -> p50=s[50]=51, p95=s[95]=96, p99=s[99]=100
    assert result["p50_latency_ms"] == 51
    assert result["p95_latency_ms"] == 96
    assert result["p99_latency_ms"] == 100
