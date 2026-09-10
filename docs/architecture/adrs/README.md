# Architecture Decision Records

This directory contains ADRs for the Kratos RHOAI MaaS Testing Harness.

## Format

Each ADR follows the [Michael Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions):
- **Status**: Accepted / Proposed / Deprecated / Superseded
- **Context**: the problem and constraints that motivated the decision
- **Decision**: what was chosen and why
- **Consequences**: trade-offs, positive and negative

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-single-container-image.md) | Single Container Image for API Server and Job Runner | Accepted |
| [ADR-002](ADR-002-kubernetes-jobs-per-run.md) | Kubernetes Job per Scenario Run | Accepted |
| [ADR-003](ADR-003-task-abc-deferred-cleanup.md) | Task ABC with Deferred, Scenario-wide Cleanup | Accepted |
| [ADR-004](ADR-004-shared-state-inter-task-communication.md) | shared_state Dict for Inter-task Communication | Accepted |
| [ADR-005](ADR-005-tiered-config.md) | Two-level Tiered Configuration (Global ConfigMap + Scenario YAML) | Accepted |
| [ADR-006](ADR-006-sqlite-pvc-results-storage.md) | SQLite on PVC for Run History and Results | Accepted |
| [ADR-007](ADR-007-sse-log-streaming.md) | Server-Sent Events for Live Log Streaming | Accepted |
| [ADR-008](ADR-008-service-account-token-auth.md) | Service Account Token for MaaS API Authentication | Accepted |
| [ADR-009](ADR-009-maas-subscription-via-crd.md) | MaaSSubscription Rate Limits via Kubernetes CRD | Accepted |
| [ADR-010](ADR-010-scenario-yaml-inline-assertions.md) | Scenario YAML with Inline Assertions | Accepted |
| [ADR-011](ADR-011-react-patternfly-frontend.md) | React + TypeScript + PatternFly Frontend | Accepted |
| [ADR-012](ADR-012-send-requests-overridable-url-token.md) | send_requests with Overridable URL and Token (Enabling Direct Inference) | Accepted |
| [ADR-013](ADR-013-realtime-assertion-evaluation.md) | Real-time Assertion Evaluation During Run Execution | Accepted |
| [ADR-014](ADR-014-maas-metrics-cross-validation.md) | MaaS Metrics Cross-Validation via Prometheus Baseline Delta | Accepted |
| [ADR-015](ADR-015-promql-native-assertions.md) | PromQL-Native Assertions | Accepted |
| [ADR-016](ADR-016-graceful-run-stop.md) | Graceful Run Stop via Pod Delete + SIGTERM Handler | Accepted |
