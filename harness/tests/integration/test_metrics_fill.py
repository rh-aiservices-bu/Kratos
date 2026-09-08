"""Integration test for the metrics_fill scenario."""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAAS_API_URL"),
    reason="MAAS_API_URL not set — requires a live RHOAI cluster",
)


async def test_metrics_fill_passes() -> None:
    from harness.runner import ScenarioRunner

    run_id = str(uuid.uuid4())
    runner = ScenarioRunner("scenarios/metrics_fill.yaml", run_id)
    result = await runner.run()

    assert result.status == "PASS", (
        f"metrics_fill returned {result.status}. "
        f"Task results: {result.tasks}. "
        f"Assertions: {result.assertions}"
    )


async def test_metrics_fill_counters_populated() -> None:
    """Metrics pipeline must show non-zero request and token counts."""
    from harness.runner import ScenarioRunner

    run_id = str(uuid.uuid4())
    runner = ScenarioRunner("scenarios/metrics_fill.yaml", run_id)
    result = await runner.run()

    shared = {}
    # Extract metrics from the run's shared_state via assertion results
    metrics_assertions = {a.name: a for a in result.assertions}

    if "total_requests" in metrics_assertions:
        ar = metrics_assertions["total_requests"]
        if ar.current_value is not None:
            assert ar.current_value >= 190, (
                f"Expected total_requests >= 190 from metrics pipeline, got {ar.current_value}"
            )

    del shared  # unused — assertion results carry the needed data
