# ADR-008: Service Account Token for MaaS API Authentication

## Status

Accepted

## Context

Kratos needs to authenticate to the MaaS REST API (for key lifecycle operations) and to the Kubernetes API (for creating Jobs, watching pods, managing `MaaSSubscription` CRs). Two broad authentication strategies were considered:

1. **Service Account (SA) token**: a dedicated SA is granted the necessary roles at deploy time. The token is auto-mounted into every pod at `/var/run/secrets/kubernetes.io/serviceaccount/token`. Both the Kubernetes client and the MaaS API accept this OpenShift bearer token.
2. **Per-user OIDC token passthrough**: the UI authenticates the human operator, and their OIDC token is forwarded through the API server into the Job pods, so all actions are performed as that user.

The intended user of Kratos is an admin who has already configured the namespace and RBAC. The harness operates through RHOAI's user-facing APIs (not raw cluster admin operations), but it does require elevated permissions (rhoai-admin equivalent) to provision API keys and manage subscriptions.

## Decision

Use a **dedicated Kubernetes Service Account** with the necessary permissions granted via a `Role`/`ClusterRoleBinding`. The SA token is auto-mounted and used for both MaaS API calls (as an OpenShift bearer token) and Kubernetes API calls. No credentials are stored in Secrets or passed through the UI.

Required permissions:
- `rhoai-admin` ClusterRole (or equivalent) — to call MaaS API and manage `MaaSSubscription` CRs
- `create`, `get`, `list`, `watch` on `jobs` and `pods` in the harness namespace

## Consequences

**Positive:**
- Zero credential management: no secrets to rotate, no token storage, no UI auth flow to implement.
- The SA token is available in every Job pod automatically — tasks can use it without any setup.
- All actions are auditable under a single, clearly named service account (`kratos-runner` or similar).

**Negative:**
- All runs execute with the same elevated SA permissions regardless of who triggered them from the UI. There is no per-user permission enforcement within Kratos.
- If the SA token is compromised (e.g. via a malicious scenario YAML), it has broad MaaS and namespace permissions.

**Neutral:**
- Per-user OIDC token passthrough is listed as a future feature (ADR supersedes this in a future iteration if per-user enforcement becomes a requirement).
- The SA is namespace-scoped; the `rhoai-admin` ClusterRole binding limits blast radius to RHOAI operations.
