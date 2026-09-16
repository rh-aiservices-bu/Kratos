"""Read-only access to the live MaaS domain model (subscriptions, models) and
the resources they reference, for the "MaaS Setup" overview in the UI.

Every list/get call is wrapped so a missing CRD or missing RBAC degrades to
an ``unavailable`` result for just that resource type rather than raising —
one section being unreadable must not blank out a section backed by a
different RBAC grant. See docs/architecture/adrs/ADR-017-maas-cluster-visibility.md
and deploy/rbac-maas-readonly.yaml for the permissions this relies on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml
from kubernetes import client as k8s, config as k8s_cfg
from kubernetes.client import ApiException

_MAAS_GROUP = "maas.opendatahub.io"
_MAAS_VERSION = "v1alpha1"
_KSERVE_GROUP = "serving.kserve.io"
_KSERVE_VERSION = "v1alpha2"
_OPENSHIFT_USER_GROUP = "user.openshift.io"
_OPENSHIFT_USER_VERSION = "v1"
_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

_kube_loaded = False


def _kube() -> None:
    global _kube_loaded
    if _kube_loaded:
        return
    try:
        k8s_cfg.load_incluster_config()
    except k8s_cfg.ConfigException:
        k8s_cfg.load_kube_config()
    _kube_loaded = True


def sa_token() -> str:
    try:
        return Path(_SA_TOKEN_PATH).read_text().strip()
    except OSError:
        return ""


def maas_api_url() -> str:
    return os.environ.get("MAAS_API_URL", "")


@dataclass
class ResourceList:
    """Result of a best-effort cluster read."""

    available: bool
    items: list[dict] = field(default_factory=list)
    reason: str | None = None  # "forbidden" | "not_installed" | "error_<n>"


def _reason_for(exc: ApiException) -> str:
    if exc.status == 403:
        return "forbidden"
    if exc.status == 404:
        return "not_installed"
    return f"error_{exc.status}"


def _list(group: str, version: str, plural: str) -> ResourceList:
    """List a custom resource across all namespaces (or cluster-scoped).

    Kubernetes serves this the same way `kubectl get <plural> -A` does — no
    namespace segment in the URL — for both cluster-scoped and namespaced
    CRDs, as long as the caller has a cluster-wide list grant.
    """
    _kube()
    api = k8s.CustomObjectsApi()
    try:
        result = api.list_cluster_custom_object(group=group, version=version, plural=plural)
        return ResourceList(available=True, items=result.get("items", []))
    except ApiException as exc:
        return ResourceList(available=False, reason=_reason_for(exc))
    except Exception:
        # The API server itself couldn't be reached at all (DNS/network/TLS
        # failure) — distinct from an ApiException, which means the request
        # reached a real API server and got a structured error back. Kept as
        # a short code, not str(exc), since that exception text is a raw
        # urllib3 connection error not fit for display in the UI.
        return ResourceList(available=False, reason="unreachable")


def _get(group: str, version: str, namespace: str, plural: str, name: str) -> dict | None:
    _kube()
    api = k8s.CustomObjectsApi()
    try:
        return api.get_namespaced_custom_object(
            group=group, version=version, namespace=namespace, plural=plural, name=name
        )
    except Exception:
        return None


def _condition(conditions: list[dict], cond_type: str) -> dict | None:
    for c in conditions or []:
        if c.get("type") == cond_type:
            return c
    return None


def _is_ready(conditions: list[dict], cond_type: str = "Ready") -> bool:
    cond = _condition(conditions, cond_type)
    return bool(cond and cond.get("status") == "True")


def _to_yaml(obj: dict) -> str:
    """Render a raw cluster object the same way the run-settings YAML viewer
    (api/routes/config.py) does, so "View YAML" looks identical everywhere."""
    return yaml.safe_dump(obj, sort_keys=False, default_flow_style=False)


def list_subscriptions() -> ResourceList:
    result = _list(_MAAS_GROUP, _MAAS_VERSION, "maassubscriptions")
    if not result.available:
        return result

    shaped = []
    for cr in result.items:
        meta = cr.get("metadata", {})
        spec = cr.get("spec", {})
        status = cr.get("status", {})
        annotations = meta.get("annotations", {})
        conditions = status.get("conditions", [])
        conflict_cond = _condition(conditions, "SpecPriorityDuplicate")

        shaped.append(
            {
                "name": meta.get("name"),
                "namespace": meta.get("namespace"),
                "display_name": annotations.get("openshift.io/display-name", meta.get("name")),
                "description": annotations.get("openshift.io/description", ""),
                "priority": spec.get("priority"),
                "owner": {
                    "groups": [g.get("name") for g in (spec.get("owner", {}).get("groups") or [])],
                    "users": spec.get("owner", {}).get("users") or [],
                },
                "models": [
                    {
                        "name": m.get("name"),
                        "namespace": m.get("namespace"),
                        "token_rate_limits": m.get("tokenRateLimits") or [],
                    }
                    for m in (spec.get("modelRefs") or [])
                ],
                "phase": status.get("phase"),
                "ready": _is_ready(conditions),
                "priority_conflict": bool(conflict_cond and conflict_cond.get("status") == "True"),
                "raw": cr,
                "raw_yaml": _to_yaml(cr),
            }
        )

    return ResourceList(available=True, items=shaped)


def _fetch_v1_models() -> tuple[bool, list[dict]]:
    """GET {MAAS_API_URL}/v1/models — used to cross-reference which
    subscriptions grant each model, since that reverse index isn't on the
    MaaSModelRef CR itself.
    """
    url = maas_api_url()
    token = sa_token()
    if not url or not token:
        return False, []
    try:
        resp = httpx.get(
            f"{url}/v1/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        return True, resp.json().get("data", [])
    except Exception:
        return False, []


def list_models() -> ResourceList:
    modelrefs_result = _list(_MAAS_GROUP, _MAAS_VERSION, "maasmodelrefs")
    externalmodels_result = _list(_MAAS_GROUP, _MAAS_VERSION, "externalmodels")

    if not modelrefs_result.available and not externalmodels_result.available:
        # Neither readable — report the MaaSModelRef reason since that's the
        # primary resource; ExternalModel is optional/tech-preview.
        return modelrefs_result

    _, rest_models = _fetch_v1_models()
    rest_by_owner = {m.get("owned_by"): m for m in rest_models}

    shaped = []
    for cr in modelrefs_result.items if modelrefs_result.available else []:
        meta = cr.get("metadata", {})
        spec = cr.get("spec", {})
        status = cr.get("status", {})
        annotations = meta.get("annotations", {})
        name, namespace = meta.get("name"), meta.get("namespace")
        conditions = status.get("conditions", [])

        model_ref = spec.get("modelRef", {})
        rest_entry = rest_by_owner.get(f"{namespace}/{name}")

        # "Internal" here means served through OpenShift AI itself
        # (LLMInferenceService); anything else (a future backing kind, or no
        # modelRef.kind at all) is treated as external/unknown rather than
        # silently assumed internal.
        hosting = "internal" if model_ref.get("kind") == "LLMInferenceService" else "external"

        serving = None
        llm_isvc = None
        if model_ref.get("kind") == "LLMInferenceService":
            llm_isvc = _get(
                _KSERVE_GROUP, _KSERVE_VERSION, namespace, "llminferenceservices",
                model_ref.get("name"),
            )
            if llm_isvc:
                llm_spec = llm_isvc.get("spec", {})
                llm_status = llm_isvc.get("status", {})
                containers = llm_spec.get("template", {}).get("containers", [])
                serving = {
                    "replicas": llm_spec.get("replicas"),
                    "resources": containers[0].get("resources") if containers else None,
                    "conditions": llm_status.get("conditions", []),
                }

        yaml_doc = {"maasModelRef": cr}
        if llm_isvc:
            yaml_doc["llmInferenceService"] = llm_isvc

        shaped.append(
            {
                "name": name,
                "namespace": namespace,
                "display_name": annotations.get("openshift.io/display-name", name),
                "description": annotations.get("openshift.io/description", ""),
                "kind": model_ref.get("kind"),
                "hosting": hosting,
                "backing_name": model_ref.get("name"),
                "phase": status.get("phase"),
                "ready": _is_ready(conditions),
                "endpoint": status.get("endpoint"),
                "subscriptions": [
                    {
                        "name": s.get("name"),
                        "display_name": s.get("displayName"),
                        "description": s.get("description"),
                    }
                    for s in ((rest_entry or {}).get("subscriptions") or [])
                ],
                "serving": serving,
                "raw": cr,
                "raw_yaml": _to_yaml(yaml_doc),
            }
        )

    for cr in externalmodels_result.items if externalmodels_result.available else []:
        meta = cr.get("metadata", {})
        annotations = meta.get("annotations", {})
        name, namespace = meta.get("name"), meta.get("namespace")
        shaped.append(
            {
                "name": name,
                "namespace": namespace,
                "display_name": annotations.get("openshift.io/display-name", name),
                "description": annotations.get("openshift.io/description", ""),
                "kind": "ExternalModel",
                "hosting": "external",
                "backing_name": None,
                "phase": cr.get("status", {}).get("phase"),
                "ready": False,
                "endpoint": None,
                "subscriptions": [],
                "serving": None,
                "raw": cr,
                "raw_yaml": _to_yaml(cr),
            }
        )

    return ResourceList(available=True, items=shaped)


def list_access() -> ResourceList:
    """Cross-reference subscriptions (quota), MaaSAuthPolicy (gateway access),
    and OpenShift Groups (membership) into one row per group — see Catalog
    item C in docs/architecture/maas-domain-reference.md for why both a
    subscription AND a matching auth policy are required, and what it means
    when a group has one but not the other.

    Needs subscriptions AND auth policies to do anything meaningful (the
    whole point is comparing them), so either being unreadable makes the
    section unavailable as a whole. Groups is treated as a softer
    dependency — its absence still lets us show group names, subscriptions
    and auth policies; it just can't resolve them to member usernames.
    """
    subs = list_subscriptions()
    if not subs.available:
        return subs

    auth = _list(_MAAS_GROUP, _MAAS_VERSION, "maasauthpolicies")
    if not auth.available:
        return auth

    groups = _list(_OPENSHIFT_USER_GROUP, _OPENSHIFT_USER_VERSION, "groups")
    group_users: dict[str, list[str]] | None = None
    group_raw_yaml: dict[str, str] = {}
    if groups.available:
        group_users = {
            g.get("metadata", {}).get("name"): g.get("users") or [] for g in groups.items
        }
        group_raw_yaml = {
            g.get("metadata", {}).get("name"): _to_yaml(g) for g in groups.items
        }

    shaped_auth = []
    for cr in auth.items:
        meta = cr.get("metadata", {})
        spec = cr.get("spec", {})
        status = cr.get("status", {})
        annotations = meta.get("annotations", {})
        subjects = spec.get("subjects", {})
        shaped_auth.append(
            {
                "name": meta.get("name"),
                "display_name": annotations.get("openshift.io/display-name", meta.get("name")),
                "groups": [g.get("name") for g in (subjects.get("groups") or [])],
                "users": subjects.get("users") or [],
                "models": [
                    (m.get("namespace"), m.get("name")) for m in (spec.get("modelRefs") or [])
                ],
                "ready": _is_ready(status.get("conditions", [])),
                "raw_yaml": _to_yaml(cr),
            }
        )

    group_names: set[str] = set()
    for sub in subs.items:
        group_names.update(sub["owner"]["groups"])
    for ap in shaped_auth:
        group_names.update(ap["groups"])
    if group_users is not None:
        group_names.update(group_users.keys())

    rows = []
    for name in sorted(group_names):
        subs_for_group = [s for s in subs.items if name in s["owner"]["groups"]]
        auth_for_group = [a for a in shaped_auth if name in a["groups"]]

        quota_models = {(m["namespace"], m["name"]) for s in subs_for_group for m in s["models"]}
        access_models = {m for a in auth_for_group for m in a["models"]}

        rows.append(
            {
                "name": name,
                "users": group_users.get(name) if group_users is not None else None,
                "raw_yaml": group_raw_yaml.get(name),
                "subscriptions": [
                    {
                        "name": s["name"],
                        "display_name": s["display_name"],
                        "priority": s["priority"],
                        "raw_yaml": s["raw_yaml"],
                    }
                    for s in subs_for_group
                ],
                "auth_policies": [
                    {
                        "name": a["name"],
                        "display_name": a["display_name"],
                        "ready": a["ready"],
                        "raw_yaml": a["raw_yaml"],
                    }
                    for a in auth_for_group
                ],
                "quota_without_access": sorted(f"{ns}/{n}" for ns, n in quota_models - access_models),
                "access_without_quota": sorted(f"{ns}/{n}" for ns, n in access_models - quota_models),
            }
        )

    return ResourceList(available=True, items=rows)
