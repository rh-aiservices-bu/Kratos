import re
from dataclasses import dataclass, field
from typing import Any, Literal

AssertionStatus = Literal["PENDING", "PASSING", "FAILING"]

_OPERATORS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "==": lambda a, b: a == b,
}
_EXPR_RE = re.compile(r"^\s*(<=|>=|<|>|==)\s*(.+?)\s*$")


@dataclass
class TaskResult:
    task_name: str
    status: Literal["PASS", "FAIL", "CANCELLED"]
    duration_ms: float
    error: str | None = None
    assertions: list["AssertionResult"] = field(default_factory=list)


@dataclass
class AssertionResult:
    name: str
    expression: str
    status: AssertionStatus
    current_value: float | None = None
    expected_value: float | None = None


@dataclass
class RunResult:
    run_id: str
    scenario_name: str
    status: Literal["PASS", "FAIL", "CANCELLED"]
    tasks: list[TaskResult] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    duration_ms: float = 0.0


def _extract_metric(name: str, shared_state: dict) -> float | None:
    for namespace in ("inference_results", "metrics"):
        ns = shared_state.get(namespace, {})
        if name in ns:
            return float(ns[name])
    if name in shared_state:
        try:
            return float(shared_state[name])
        except (TypeError, ValueError):
            pass
    return None


def _extract_namespaced(ref: str, shared_state: dict) -> float | None:
    """Resolve an explicit 'namespace.key' reference, e.g. 'metrics.total_requests_delta'."""
    namespace, _, key = ref.partition(".")
    if not key:
        return None
    ns = shared_state.get(namespace, {})
    if not isinstance(ns, dict) or key not in ns:
        return None
    try:
        return float(ns[key])
    except (TypeError, ValueError):
        return None


def _evaluate_match_assertion(name: str, spec: dict[str, Any], shared_state: dict) -> AssertionResult:
    """Compare two live metrics against each other within a tolerance band.

    spec: {"compare": "namespace.key", "to": "namespace.key", "tolerance_pct": <float>}
    """
    expression = f"{spec.get('compare')} ~= {spec.get('to')} (±{spec.get('tolerance_pct', 0)}%)"
    observed = _extract_namespaced(str(spec.get("compare", "")), shared_state)
    expected = _extract_namespaced(str(spec.get("to", "")), shared_state)
    if observed is None or expected is None:
        return AssertionResult(name=name, expression=expression, status="PENDING")

    tolerance_pct = float(spec.get("tolerance_pct", 0))
    allowed = tolerance_pct / 100 * max(abs(expected), 1)
    passing = abs(observed - expected) <= allowed
    return AssertionResult(
        name=name,
        expression=expression,
        status="PASSING" if passing else "FAILING",
        current_value=observed,
        expected_value=expected,
    )


def _evaluate_promql_assertion(name: str, spec: dict[str, Any], shared_state: dict) -> AssertionResult:
    """Assertion backed by a live PromQL query.

    spec: {"promql": "<promql text>", "expect": "<op> <value>"} for a plain threshold,
    or {"promql": ..., "compare_to": "namespace.key", "tolerance_pct": <float>} to
    cross-check against a harness-side value the same way the match form does.

    The runner (harness/runner.py) is responsible for actually firing spec["promql"]
    each poll tick — resolving ${baseline.x}/${harness.x} template variables first —
    and writing the result into shared_state["metrics"][name]. This function only
    reads that already-fetched value; it never talks to Prometheus itself, keeping
    this module a pure, synchronous evaluator like every other assertion form.
    """
    promql = spec.get("promql", "")
    observed = shared_state.get("metrics", {}).get(name)
    if observed is None:
        return AssertionResult(name=name, expression=promql, status="PENDING")
    observed = float(observed)

    if "compare_to" in spec:
        expected = _extract_namespaced(str(spec.get("compare_to", "")), shared_state)
        if expected is None:
            return AssertionResult(name=name, expression=promql, status="PENDING")
        tolerance_pct = float(spec.get("tolerance_pct", 0))
        allowed = tolerance_pct / 100 * max(abs(expected), 1)
        passing = abs(observed - expected) <= allowed
        return AssertionResult(
            name=name,
            expression=f"{promql} ~= {spec.get('compare_to')} (±{tolerance_pct}%)",
            status="PASSING" if passing else "FAILING",
            current_value=observed,
            expected_value=expected,
        )

    expect = spec.get("expect")
    if expect is None:
        raise ValueError(f"promql assertion {name!r} needs either 'expect' or 'compare_to'")
    m = _EXPR_RE.match(expect)
    if not m:
        raise ValueError(f"Cannot parse assertion expression: {expect!r}")
    op = _OPERATORS[m.group(1)]
    passing = op(observed, float(m.group(2)))
    return AssertionResult(
        name=name,
        expression=f"{promql} {expect}",
        status="PASSING" if passing else "FAILING",
        current_value=observed,
    )


def evaluate_assertion(
    name: str, expression: str | dict[str, Any], shared_state: dict
) -> AssertionResult:
    if isinstance(expression, dict):
        if "promql" in expression:
            return _evaluate_promql_assertion(name, expression, shared_state)
        return _evaluate_match_assertion(name, expression, shared_state)

    value = _extract_metric(name, shared_state)
    if value is None:
        return AssertionResult(name=name, expression=expression, status="PENDING")

    m = _EXPR_RE.match(expression)
    if not m:
        raise ValueError(f"Cannot parse assertion expression: {expression!r}")

    op_str, rhs_str = m.group(1), m.group(2)
    op = _OPERATORS[op_str]
    passing = op(value, float(rhs_str))
    return AssertionResult(
        name=name,
        expression=expression,
        status="PASSING" if passing else "FAILING",
        current_value=value,
    )


def evaluate_all_assertions(
    assertions: dict[str, str | dict[str, Any]], shared_state: dict
) -> list[AssertionResult]:
    return [evaluate_assertion(name, expr, shared_state) for name, expr in assertions.items()]


def compute_run_status(
    task_results: list[TaskResult], assertion_results: list[AssertionResult]
) -> Literal["PASS", "FAIL"]:
    if any(t.status == "FAIL" for t in task_results):
        return "FAIL"
    if any(a.status == "FAILING" for a in assertion_results):
        return "FAIL"
    return "PASS"
