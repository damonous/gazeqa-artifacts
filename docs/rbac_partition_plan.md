# RBAC Partition Plan (FR-013)

This note captures the plan and evidence for multi-tenant separation across the GazeQA CLI and API.

## Token Registry and Roles

- `GAZEQA_API_TOKEN_REGISTRY` provides a JSON map of bearer tokens to `(organization_slug, actor_role, scopes)`.
- Default role scopes:
  - `qa_runner`: `runs:create`, `runs:read`, `runs:events`
  - `qa_viewer`: `runs:read`, `runs:events`
  - `admin` (optional): adds `runs:read:all` for cross-org operations.
- Tokens without `runs:create` (e.g. viewers) receive `403 Forbidden` when attempting POST `/runs`.
- All reads (list/detail/events) are restricted to matching `organization_slug` unless `runs:read:all` is granted.

## Storage Layout

- Runs now persist under `artifacts/runs/<organization_slug>/<RUN-ID>/` with a shared `run_index.json` mapping `run_id` to organization metadata.
- `RunService`, artifact manifest generation, and observability emit paths that resolve via the index to prevent directory traversal.
- Authentication orchestrator receives the resolved run directory to keep stored secrets under the correct tenant.

## Evidence

- Signed artifact URLs embed `organization_slug` alongside `run_id` and paths to block cross-tenant reuse.
- Org-scoped run manifest: `artifacts/runs/acme-qa/RUN-4F3A52027D4A/run_manifest.json`
- Cross-tenant list denial: `artifacts/runs/acme-qa/RUN-4F3A52027D4A/logs/api_get_runs.json`
- Viewer-role enforcement: `artifacts/runs/acme-qa/RUN-4F3A52027D4A/logs/api_post_runs_viewer.log`
- Legacy migration helper: call `RunService.rebuild_index(move_legacy=True)` to relocate `artifacts/runs/RUN-*` into `artifacts/runs/<slug>/` and regenerate `run_index.json`.
- CLI utility: `python tools/rebuild_run_index.py --move-legacy artifacts/runs` wraps the helper for operational use (see `docs/rebuild_run_index.md`).
- Telemetry events now include `organization_slug` so Prometheus/Grafana dashboards can facet metrics by tenant.

## Follow-ups

1. Harden token storage by moving registry to secret manager (out of scope for this iteration).
2. Extend UI to surface organization context alongside run metadata.
3. Automate migration for legacy runs that still reside at `artifacts/runs/<RUN-ID>/`.
