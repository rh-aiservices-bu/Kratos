import pytest

from harness.result import (
    AssertionResult,
    RunResult,
    TaskResult,
    compute_run_status,
    evaluate_all_assertions,
    evaluate_assertion,
)


def test_pending_when_metric_absent() -> None:
    r = evaluate_assertion("error_rate_pct", "< 5", shared_state={})
    assert r.status == "PENDING"
    assert r.current_value is None


def test_passing_less_than() -> None:
    state = {"inference_results": {"error_rate_pct": 2.0}}
    r = evaluate_assertion("error_rate_pct", "< 5", state)
    assert r.status == "PASSING"
    assert r.current_value == 2.0


def test_failing_less_than() -> None:
    state = {"inference_results": {"error_rate_pct": 10.0}}
    assert evaluate_assertion("error_rate_pct", "< 5", state).status == "FAILING"


def test_greater_than_passing() -> None:
    state = {"inference_results": {"throughput_rps": 15.0}}
    assert evaluate_assertion("throughput_rps", "> 10", state).status == "PASSING"


def test_greater_than_failing() -> None:
    state = {"inference_results": {"throughput_rps": 5.0}}
    assert evaluate_assertion("throughput_rps", "> 10", state).status == "FAILING"


def test_less_than_or_equal_passing() -> None:
    state = {"inference_results": {"throughput_rps": 10.0}}
    assert evaluate_assertion("throughput_rps", "<= 10", state).status == "PASSING"


def test_less_than_or_equal_failing() -> None:
    state = {"inference_results": {"throughput_rps": 11.0}}
    assert evaluate_assertion("throughput_rps", "<= 10", state).status == "FAILING"


def test_greater_than_or_equal_passing() -> None:
    state = {"inference_results": {"total_requests": 95.0}}
    assert evaluate_assertion("total_requests", ">= 95", state).status == "PASSING"


def test_greater_than_or_equal_failing() -> None:
    state = {"inference_results": {"total_requests": 94.0}}
    assert evaluate_assertion("total_requests", ">= 95", state).status == "FAILING"


def test_equal_passing() -> None:
    state = {"inference_results": {"fail_count": 0.0}}
    assert evaluate_assertion("fail_count", "== 0", state).status == "PASSING"


def test_equal_failing() -> None:
    state = {"inference_results": {"fail_count": 1.0}}
    assert evaluate_assertion("fail_count", "== 0", state).status == "FAILING"


def test_invalid_expression_raises() -> None:
    state = {"inference_results": {"x": 1.0}}
    with pytest.raises(ValueError, match="Cannot parse assertion expression"):
        evaluate_assertion("x", "!= 5", state)


def test_metrics_namespace() -> None:
    state = {"metrics": {"total_tokens": 500.0}}
    r = evaluate_assertion("total_tokens", ">= 100", state)
    assert r.status == "PASSING"


def test_evaluate_all_mixed_states() -> None:
    state = {"inference_results": {"error_rate_pct": 2.0}}
    assertions = {"error_rate_pct": "< 5", "missing_metric": "> 0"}
    results = {r.name: r for r in evaluate_all_assertions(assertions, state)}
    assert results["error_rate_pct"].status == "PASSING"
    assert results["missing_metric"].status == "PENDING"


def test_run_status_pass() -> None:
    tasks = [TaskResult("t1", "PASS", 100.0)]
    assertions = [AssertionResult("x", "< 5", "PASSING", 2.0)]
    assert compute_run_status(tasks, assertions) == "PASS"


def test_run_status_pass_no_assertions() -> None:
    tasks = [TaskResult("t1", "PASS", 100.0)]
    assert compute_run_status(tasks, []) == "PASS"


def test_run_status_fail_on_task_failure() -> None:
    tasks = [TaskResult("t1", "FAIL", 100.0, error="oops")]
    assert compute_run_status(tasks, []) == "FAIL"


def test_run_status_fail_on_failing_assertion() -> None:
    tasks = [TaskResult("t1", "PASS", 100.0)]
    assertions = [AssertionResult("x", "< 5", "FAILING", 10.0)]
    assert compute_run_status(tasks, assertions) == "FAIL"


def test_run_status_pass_with_pending_assertions() -> None:
    tasks = [TaskResult("t1", "PASS", 100.0)]
    assertions = [AssertionResult("x", "< 5", "PENDING")]
    assert compute_run_status(tasks, assertions) == "PASS"
