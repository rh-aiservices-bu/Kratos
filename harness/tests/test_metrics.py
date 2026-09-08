import pytest
from pytest_httpx import HTTPXMock

from harness.tasks.base import TaskContext
from harness.tasks.metrics import CheckMaasMetricsTask


def _make_ctx(config: dict | None = None, shared_state: dict | None = None) -> TaskContext:
    async def _emit() -> None:
        pass

    return TaskContext(
        run_id="test-001",
        scenario_name="test",
        maas_api_url="http://maas.test",
        sa_token="test-token",
        shared_state=shared_state or {},
        config=config or {},
        assertions={},
        emit_assertion_state=_emit,
    )


async def test_check_maas_metrics_stub_returns_zeroes(capsys: pytest.CaptureFixture) -> None:
    task = CheckMaasMetricsTask("check_maas_metrics", {})
    ctx = _make_ctx()
    result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["metrics"]["total_requests"] == 0
    assert ctx.shared_state["metrics"]["total_tokens"] == 0
    out = capsys.readouterr().out
    assert "stub zeroes" in out


async def test_check_maas_metrics_prints_summary(capsys: pytest.CaptureFixture) -> None:
    task = CheckMaasMetricsTask("check_maas_metrics", {})
    ctx = _make_ctx()
    await task.run(ctx)
    out = capsys.readouterr().out
    assert "total_requests" in out
    assert "total_tokens" in out


async def test_check_maas_metrics_stores_in_shared_state() -> None:
    task = CheckMaasMetricsTask("check_maas_metrics", {})
    ctx = _make_ctx()
    await task.run(ctx)
    assert "metrics" in ctx.shared_state


async def test_check_maas_metrics_fetches_from_url(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://metrics.test/metrics",
        json={"total_requests": 42, "total_tokens": 100},
    )

    task = CheckMaasMetricsTask(
        "check_maas_metrics", {"metrics_url": "http://metrics.test/metrics"}
    )
    ctx = _make_ctx()
    result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["metrics"]["total_requests"] == 42
    assert ctx.shared_state["metrics"]["total_tokens"] == 100


async def test_check_maas_metrics_handles_fetch_error(capsys: pytest.CaptureFixture) -> None:
    """Fetch failure is logged but task still passes with zeroes."""
    task = CheckMaasMetricsTask(
        "check_maas_metrics", {"metrics_url": "http://unreachable.test/metrics"}
    )
    ctx = _make_ctx()
    result = await task.run(ctx)

    assert result.status == "PASS"
    assert ctx.shared_state["metrics"]["total_requests"] == 0
    out = capsys.readouterr().out
    assert "could not fetch" in out


async def test_check_maas_metrics_cleanup_is_noop() -> None:
    task = CheckMaasMetricsTask("check_maas_metrics", {})
    ctx = _make_ctx()
    await task.cleanup(ctx)
