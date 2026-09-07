import asyncio
import textwrap
from pathlib import Path

import pytest

from harness.result import TaskResult
from harness.runner import ScenarioRunner
from harness.tasks.base import Task, TaskContext
from harness.tasks.registry import REGISTRY


def _write(tmp_path: Path, content: str) -> str:
    f = tmp_path / "scenario.yaml"
    f.write_text(textwrap.dedent(content))
    return str(f)


def test_task_ordering(tmp_path: Path) -> None:
    order: list[str] = []

    class _OrderedTask(Task):
        async def run(self, ctx: TaskContext) -> TaskResult:
            order.append(self.name)
            return TaskResult(task_name=self.name, status="PASS", duration_ms=0)

        async def cleanup(self, ctx: TaskContext) -> None:
            pass

    REGISTRY["_ordered_a"] = _OrderedTask
    REGISTRY["_ordered_b"] = _OrderedTask

    try:
        path = _write(tmp_path, """
            name: test_order
            config: {}
            tasks:
              - name: _ordered_a
                params: {}
              - name: _ordered_b
                params: {}
            assertions: {}
        """)
        result = asyncio.run(ScenarioRunner(path, "order-001").run())
        assert order == ["_ordered_a", "_ordered_b"]
        assert result.status == "PASS"
    finally:
        REGISTRY.pop("_ordered_a", None)
        REGISTRY.pop("_ordered_b", None)


def test_cleanup_runs_on_failure(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = _write(tmp_path, """
        name: test_cleanup
        config: {}
        tasks:
          - name: stub_pass
            params: {}
          - name: stub_fail
            params: {}
        assertions: {}
    """)
    result = asyncio.run(ScenarioRunner(path, "cleanup-001").run())

    assert result.status == "FAIL"
    out = capsys.readouterr().out
    assert "cleanup" in out


def test_cleanup_runs_in_reverse_order(tmp_path: Path) -> None:
    cleanup_order: list[str] = []

    class _TrackTask(Task):
        async def run(self, ctx: TaskContext) -> TaskResult:
            return TaskResult(task_name=self.name, status="PASS", duration_ms=0)

        async def cleanup(self, ctx: TaskContext) -> None:
            cleanup_order.append(self.name)

    REGISTRY["_track_a"] = _TrackTask
    REGISTRY["_track_b"] = _TrackTask

    try:
        path = _write(tmp_path, """
            name: test_reverse
            config: {}
            tasks:
              - name: _track_a
                params: {}
              - name: _track_b
                params: {}
            assertions: {}
        """)
        asyncio.run(ScenarioRunner(path, "reverse-001").run())
        assert cleanup_order == ["_track_b", "_track_a"]
    finally:
        REGISTRY.pop("_track_a", None)
        REGISTRY.pop("_track_b", None)


def test_cleanup_runs_for_all_tasks_even_on_early_failure(tmp_path: Path) -> None:
    """All tasks receive cleanup calls even if an earlier task failed."""
    cleaned: list[str] = []

    class _EarlyFail(Task):
        async def run(self, ctx: TaskContext) -> TaskResult:
            raise RuntimeError("fails early")

        async def cleanup(self, ctx: TaskContext) -> None:
            cleaned.append(self.name)

    class _NeverRan(Task):
        async def run(self, ctx: TaskContext) -> TaskResult:
            return TaskResult(task_name=self.name, status="PASS", duration_ms=0)

        async def cleanup(self, ctx: TaskContext) -> None:
            cleaned.append(self.name)

    REGISTRY["_early_fail"] = _EarlyFail
    REGISTRY["_never_ran"] = _NeverRan

    try:
        path = _write(tmp_path, """
            name: test_all_cleanup
            config: {}
            tasks:
              - name: _early_fail
                params: {}
              - name: _never_ran
                params: {}
            assertions: {}
        """)
        result = asyncio.run(ScenarioRunner(path, "all-cleanup-001").run())
        assert result.status == "FAIL"
        assert "_early_fail" in cleaned
        assert "_never_ran" in cleaned
    finally:
        REGISTRY.pop("_early_fail", None)
        REGISTRY.pop("_never_ran", None)


def test_assertion_state_progression(tmp_path: Path) -> None:
    class _MetricTask(Task):
        async def run(self, ctx: TaskContext) -> TaskResult:
            ctx.shared_state.setdefault("inference_results", {})["error_rate_pct"] = 1.0
            await ctx.emit_assertion_state()
            return TaskResult(task_name=self.name, status="PASS", duration_ms=0)

        async def cleanup(self, ctx: TaskContext) -> None:
            pass

    REGISTRY["_metric_task"] = _MetricTask

    try:
        path = _write(tmp_path, """
            name: test_assertions
            config: {}
            tasks:
              - name: _metric_task
                params: {}
            assertions:
              error_rate_pct: "< 5"
        """)
        result = asyncio.run(ScenarioRunner(path, "assert-001").run())
        assert result.status == "PASS"
        assert len(result.assertions) == 1
        assert result.assertions[0].status == "PASSING"
        assert result.assertions[0].current_value == 1.0
    finally:
        REGISTRY.pop("_metric_task", None)


def test_unknown_task_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, """
        name: test_unknown
        config: {}
        tasks:
          - name: nonexistent_task
            params: {}
        assertions: {}
    """)
    with pytest.raises(KeyError):
        asyncio.run(ScenarioRunner(path, "unknown-001").run())


def test_stub_scenario_passes() -> None:
    result = asyncio.run(ScenarioRunner("scenarios/stub.yaml", "stub-001").run())
    assert result.status == "PASS"
    assert len(result.tasks) == 2
    assert all(t.status == "PASS" for t in result.tasks)


def test_stub_failing_scenario_produces_fail_with_cleanup(
    capsys: pytest.CaptureFixture,
) -> None:
    result = asyncio.run(ScenarioRunner("scenarios/stub_failing.yaml", "stubfail-001").run())
    assert result.status == "FAIL"
    out = capsys.readouterr().out
    assert "[stub_pass] cleanup" in out
    assert "[stub_fail] cleanup" in out
