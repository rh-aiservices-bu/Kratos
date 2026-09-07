# ADR-012: send_requests with Overridable URL and Token (Enabling Direct Inference)

## Status

Accepted

## Context

The `direct_inference` scenario needs to send inference requests directly to a model serving endpoint — bypassing the MaaS gateway — using a caller-supplied URL and auth token. This is useful for:
- Testing the underlying model serving layer independently of MaaS routing.
- Comparing MaaS-routed latency vs direct latency for the same model.

Options considered:

1. **Separate task class `send_direct_requests`**: a new task that accepts `url` and `token` as params. Duplicates most of `send_requests` logic.
2. **Overridable params on existing `send_requests`**: add optional `url` and `token` params to the existing task. When provided, they override the context defaults (`maas_api_url` + SA token). When absent, behaviour is unchanged.
3. **`direct_inference` as a scenario using a specialized task**: design a purpose-built task for the direct use case. Higher coupling, less reuse.

## Decision

Extend **`send_requests`** with optional `url` and `token` params that, when provided, override the `TaskContext` defaults:

```yaml
- name: send_requests
  params:
    url: "${config.target_url}"
    token: "${config.target_token}"
    count: "${config.request_count}"
    concurrency: "${config.concurrency}"
```

When `url` is omitted, the task resolves the endpoint from the MaaS model discovery API (`GET /v1/models`) as usual. When `token` is omitted, the SA token from `TaskContext` is used. Both must be supplied together for the direct inference case.

The `direct_inference` scenario uses this mechanism and skips `provision_api_key` entirely — there is no key provisioning and no cleanup.

## Consequences

**Positive:**
- No code duplication: one task class handles both MaaS-routed and direct inference.
- The `direct_inference` scenario YAML is minimal — just a single `send_requests` task with two extra params.
- Future scenarios can mix and match: provision a key for one request batch, then compare with a direct call, all in the same scenario.

**Negative:**
- The `send_requests` task now has two distinct operating modes governed by optional params. The implementation must clearly document when `url`/`token` are required together.
- `target_url` and `target_token` have no default values in `direct_inference` and are marked required; the harness config loader should validate their presence before the task runs and fail fast with a descriptive error.

**Neutral:**
- `direct_inference` does not call `check_metrics` because it bypasses MaaS — there are no MaaS-side metrics to validate for a direct inference call.
- The overridable params do not affect any existing scenario; MaaS-based scenarios continue to work exactly as before.
