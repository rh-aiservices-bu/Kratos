import pathlib
import re

import pytest
import yaml

from harness.config import load_scenario
from harness.tasks.registry import REGISTRY

_SCENARIO_DIR = pathlib.Path("scenarios")
_SCENARIO_PATHS = sorted(
    p for p in _SCENARIO_DIR.glob("*.yaml") if not p.stem.startswith("stub")
)
_REQUIRED_FIELDS = {"name", "description", "tasks", "cleanup"}
# ${baseline.x}/${harness.x} (ADR-015) are deliberately left unresolved by
# load_scenario() — the runner resolves them later, on its own schedule (baseline
# once after the pre-run snapshot, harness on every poll tick) — so they're expected
# to survive here, unlike ${config.x}, which must always be fully resolved by load time.
_ALLOWED_UNRESOLVED_PREFIXES = ("${baseline.", "${harness.")
# Mirrors the fixed display order in ui/src/components/ScenarioList.tsx — keeps
# the two lists from drifting apart silently. "Custom" is the API's own
# default for any scenario with no `category:` field (api/routes/scenarios.py),
# so it's deliberately not required on any file here.
_KNOWN_CATEGORIES = {
    "Load Testing",
    "Rate Limiting",
    "Access Control",
    "Metrics Validation",
    "API Key Lifecycle",
    "Platform Health",
    "Custom",
}


def test_exactly_twelve_production_scenarios() -> None:
    assert len(_SCENARIO_PATHS) == 12, (
        f"Expected 12 scenario files, found {len(_SCENARIO_PATHS)}: "
        f"{[p.name for p in _SCENARIO_PATHS]}"
    )


@pytest.mark.parametrize("path", _SCENARIO_PATHS, ids=[p.stem for p in _SCENARIO_PATHS])
def test_scenario_name_matches_filename(path: pathlib.Path) -> None:
    raw = yaml.safe_load(path.read_text())
    assert raw["name"] == path.stem, (
        f"{path.name}: expected name={path.stem!r}, got {raw['name']!r}"
    )


@pytest.mark.parametrize("path", _SCENARIO_PATHS, ids=[p.stem for p in _SCENARIO_PATHS])
def test_scenario_has_required_fields(path: pathlib.Path) -> None:
    raw = yaml.safe_load(path.read_text())
    missing = _REQUIRED_FIELDS - set(raw)
    assert not missing, f"{path.name}: missing fields {missing}"
    assert raw["cleanup"] == "automatic"


@pytest.mark.parametrize("path", _SCENARIO_PATHS, ids=[p.stem for p in _SCENARIO_PATHS])
def test_scenario_loads_and_resolves(path: pathlib.Path) -> None:
    scenario = load_scenario(str(path))
    resolved_str = str(scenario)
    for token in re.findall(r"\$\{[^}]+\}", resolved_str):
        assert token.startswith(_ALLOWED_UNRESOLVED_PREFIXES), (
            f"{path.name}: unresolved placeholder {token!r} remains after load_scenario"
        )


@pytest.mark.parametrize("path", _SCENARIO_PATHS, ids=[p.stem for p in _SCENARIO_PATHS])
def test_scenario_tasks_all_in_registry(path: pathlib.Path) -> None:
    scenario = load_scenario(str(path))
    for task_def in scenario["tasks"]:
        assert task_def["name"] in REGISTRY, (
            f"{path.name}: task {task_def['name']!r} is not registered"
        )


@pytest.mark.parametrize("path", _SCENARIO_PATHS, ids=[p.stem for p in _SCENARIO_PATHS])
def test_scenario_declares_known_category(path: pathlib.Path) -> None:
    raw = yaml.safe_load(path.read_text())
    category = raw.get("category")
    assert category in _KNOWN_CATEGORIES, (
        f"{path.name}: category {category!r} not in {sorted(_KNOWN_CATEGORIES)} "
        "— update both this test and ui/src/components/ScenarioList.tsx together"
    )


def test_kustomization_scenarios_configmap_matches_directory() -> None:
    """kustomization.yaml's configMapGenerator lists scenario files by hand
    (not a glob, unlike this test's own _SCENARIO_PATHS) — a new scenario
    added to scenarios/ without a matching line here silently never reaches
    the cluster's maaspal-scenarios ConfigMap. Bitten by exactly this twice
    already (access_denied_no_policy, then api_key_lifecycle); this test
    exists so a third time fails CI instead of a live deploy.
    """
    kustomization = yaml.safe_load(pathlib.Path("kustomization.yaml").read_text())
    generators = {g["name"]: g for g in kustomization["configMapGenerator"]}
    listed = {pathlib.Path(f).name for f in generators["maaspal-scenarios"]["files"]}
    on_disk = {p.name for p in _SCENARIO_PATHS}
    assert listed == on_disk, (
        f"kustomization.yaml's maaspal-scenarios ConfigMap file list is out of sync "
        f"with scenarios/*.yaml. Missing from kustomization.yaml: {on_disk - listed}. "
        f"Listed but not on disk: {listed - on_disk}."
    )
