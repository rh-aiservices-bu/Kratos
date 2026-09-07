# ADR-002: Kubernetes Job per Scenario Run

## Status

Accepted

## Context

Each scenario run needs to execute a sequence of tasks (HTTP calls, concurrent inference requests, Kubernetes API operations) and write results somewhere. The execution could be hosted in different ways:

- **In-process within the API server**: run tasks in an async background task or thread pool inside the FastAPI process.
- **Kubernetes Job per run**: the API server creates a new K8s Job for each run; a pod executes the scenario and exits.
- **Persistent worker pool**: a queue (e.g. Celery, RQ) with worker pods that pick up jobs.

The harness is designed to run in-cluster on OpenShift AI environments where the operator has cluster-admin-equivalent access. Runs can be long (hundreds of concurrent inference requests), resource-intensive, and should not interfere with the API server's availability.

## Decision

Create a **dedicated Kubernetes Job for every scenario run**. The API server calls the Kubernetes API to create the Job, then watches pod logs and streams them to the browser via SSE. The Job pod executes the scenario using the same container image as the API server, with `python -m harness.main` as the entrypoint.

## Consequences

**Positive:**
- Runs are fully isolated: a hung or crashing run cannot affect the API server or other runs.
- Native Kubernetes observability: pod logs, events, and status are available via standard `kubectl` tooling, not just the Kratos UI.
- No persistent worker infrastructure to manage; Jobs are ephemeral by design.
- Pod resource limits can be set per-Job independently of the API server deployment.
- The SA token is auto-mounted into the Job pod — no credential management needed.

**Negative:**
- Pod scheduling latency adds a few seconds to every run (image pull skipped if image is already cached on the node).
- Watching pod logs via the Kubernetes client introduces a streaming dependency; SSE reconnect logic is required in the UI.
- No built-in concurrency limit: many simultaneous runs create many simultaneous pods. This is acceptable for an admin-operated harness.

**Neutral:**
- Job pods write results to the shared PVC (`/data/results/<run-id>.json`) and the API server reads from there; they do not communicate directly.
