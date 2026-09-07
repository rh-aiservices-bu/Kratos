# ADR-001: Single Container Image for API Server and Job Runner

## Status

Accepted

## Context

Kratos has two distinct runtime roles:

1. **API server** — a long-running FastAPI process that serves the UI, manages run history, and creates Kubernetes Jobs.
2. **Job runner** — a short-lived process that executes a scenario (loads config, runs tasks, writes results).

These could be packaged as separate images (one per role), which would allow each to carry only its own dependencies. However, the two roles share the majority of their code: the harness task library, config loader, result types, and third-party dependencies (httpx, kubernetes client, openai SDK).

## Decision

Use a **single container image** for both roles, differentiated only by the entrypoint command:

- API server: `uvicorn api.main:app`
- Job runner: `python -m harness.main --scenario <name> --run-id <uuid>`

The image is built once, tagged, pushed once, and referenced in both the `Deployment` (API server) and the `Job` template (runner).

## Consequences

**Positive:**
- One build pipeline, one image tag to manage and promote.
- No image version skew between the API server and the jobs it spawns — they always share the same code.
- Simpler Dockerfile: no multi-stage split by role.

**Negative:**
- The API server image carries harness-only dependencies (e.g. openai SDK) it does not use at runtime, and vice versa. Image is slightly larger than strictly necessary.
- A change to the API server requires rebuilding and redeploying the job runner image (and vice versa), even if the other role is unaffected.

**Neutral:**
- The `Deployment` and `Job` manifests reference the same `image:` field; updating the tag in one place rolls out both roles simultaneously.
