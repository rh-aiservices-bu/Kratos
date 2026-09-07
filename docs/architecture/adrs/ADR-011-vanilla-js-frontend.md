# ADR-011: Vanilla JS Frontend (No Framework)

## Status

Accepted

## Context

The Kratos UI is a simple admin tool that needs to:
- Display a list of available scenarios
- Trigger a run with a button click
- Show a live log stream during a run (via SSE)
- Show a history list of past runs

Options considered:

1. **React / Vue / Angular**: full-featured SPA frameworks. Appropriate for complex UIs with rich interactivity, routing, and state management. Adds a build step (webpack/vite), `node_modules`, and ongoing dependency management.
2. **HTMX**: HTML-over-the-wire; minimal JS. Works well but requires understanding HTMX's attribute-driven model and still adds a dependency.
3. **Vanilla JS with native browser APIs**: no build step, no dependencies, no `package.json`. `fetch`, `EventSource`, and `document.querySelector` cover all UI needs listed above.

The UI surface area is small and well-defined. The audience is cluster admins, not end users, so visual polish is secondary to reliability and ease of deployment.

## Decision

Implement the frontend as **three static files** (`index.html`, `app.js`, `styles.css`) using vanilla JavaScript and native browser APIs. FastAPI serves them directly. No build step, no bundler, no npm.

Key native APIs used:
- `fetch` for `GET /api/scenarios` and `POST /api/runs`
- `EventSource` for `GET /api/runs/{id}/logs` (SSE)
- DOM manipulation via `document.createElement` / `innerHTML`

## Consequences

**Positive:**
- Zero frontend build infrastructure: no node, no bundler, no CI step for the frontend.
- Static files are served directly by FastAPI's `StaticFiles` mount — no separate web server.
- The Dockerfile stays simple: copy Python source + three static files.
- No frontend dependency CVEs or version drift to manage.

**Negative:**
- As UI complexity grows (e.g. scenario config editing, multi-run comparison), vanilla JS becomes harder to maintain than a component framework.
- No type safety in the frontend code.
- CSS is hand-written; no utility framework (Tailwind, etc.) means more verbose styling.

**Neutral:**
- If the UI grows substantially beyond its current scope, migrating to a framework is straightforward: replace the static files with a compiled SPA and update the FastAPI static mount path. The API contract is unchanged.
