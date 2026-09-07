# ADR-011: React + TypeScript + PatternFly Frontend

## Status

Accepted

## Context

The Kratos UI needs to display a scenario list, trigger runs, stream live logs via SSE, and show run history. A technology choice must be made for the frontend.

The RHOAI Dashboard (and its plugin ecosystem, including `rh-ai-community-plugins/hello-world`) is built on **React + TypeScript + PatternFly**. PatternFly is Red Hat's open-source design system and component library, used consistently across OpenShift and RHOAI UIs.

Options considered:

1. **Vanilla JS**: no framework, no build step. Simple, but does not scale well with UI complexity and produces a UI that is visually inconsistent with the RHOAI Dashboard.
2. **React + TypeScript + PatternFly**: the same stack used by RHOAI Dashboard and its plugin ecosystem. Enables visual consistency and a clear path to future integration as a Dashboard plugin.
3. **Other frameworks (Vue, Angular, HTMX)**: not used in the RHOAI ecosystem; would require a separate visual design effort and would not support plugin integration.

## Decision

Use **React + TypeScript + PatternFly** for the Kratos UI, mirroring the stack used in `rh-ai-community-plugins/hello-world`. Static assets are compiled and served by FastAPI's `StaticFiles` mount.

Key technologies:
- **React**: component model, state management, `EventSource` integration for SSE log streaming
- **TypeScript**: type safety on API response shapes and component props
- **PatternFly**: tables, cards, buttons, alerts, progress indicators — all visually consistent with RHOAI Dashboard

The frontend is still served as static files from the FastAPI `Deployment`; no separate Node.js server is introduced.

## Consequences

**Positive:**
- Visual consistency with the RHOAI Dashboard — the UI looks like it belongs in the platform.
- Clear upgrade path to a proper RHOAI Dashboard plugin (the `hello-world` template provides the scaffolding).
- TypeScript catches type errors in API response handling at build time.
- PatternFly provides accessible, enterprise-grade components out of the box.

**Negative:**
- A frontend build step is now required (`npm run build` or equivalent). The Dockerfile must install Node.js and build the frontend before the final image layer.
- `node_modules` and the build toolchain add to CI complexity relative to vanilla JS.
- Frontend dependencies (PatternFly, React, build tools) require periodic updates and CVE monitoring.

**Neutral:**
- The FastAPI backend API contract is unchanged; only the static files served at `/` change.
- If a Dashboard plugin is desired in the future, the React components and TypeScript types can be lifted into the plugin scaffolding with minimal rework.
