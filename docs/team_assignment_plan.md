# Team Assignment Plan – RTM Delivery

- Date: 2025-09-16
- Participants: Codex agent (automation/observability lead), Agent Alpha (foundation explorer lead), Agent Beta (generation & experience lead)
- Source docs: `docs/rtm_execution_plan_v1.md`, `docs/gaze_qa_rtm_v_4.json`, `docs/gaze_qa_checklist_v_4.json`

## Roles at a Glance
- **Codex agent** – safeguards automation, observability, safety/compliance, and CI integrations.
- **Agent Alpha** – owns intake, authentication, and discovery pipeline (FR-001 – FR-004).
- **Agent Beta** – leads capture, synthesis, generated outputs, delivery surfaces, and optional test execution (FR-005 – FR-010, FR-014).

## Delegated Workstreams

### Agent Alpha – Foundation Workflow (FR-001 – FR-004)
- FR-001 Task Intake and Configuration – finalize CreateRun schema, persistence, POST `/runs`, CLI wrapper.
- FR-002 Authentication and Session Persistence – CUA login, fallback automation, credential storage.
- FR-003 AI-driven Exploration – budget-aware exploration, coverage metrics, artifact capture triggers.
- FR-004 Deterministic BFS Crawl – BFS crawler, dedupe, exclusion rules, merged coverage feed.
- **Immediate actions**
  - Draft architectural outline for intake/auth flows in `docs/architecture.md` (stub) to unblock pending FRD references.
  - Produce prototype run summary + criteria JSON for FR-001/002 flows to exercise checklist updater.
  - Sync daily with Agent Beta on selector/coverage expectations to ensure downstream compatibility.

### Agent Beta – Generation & Experience (FR-005 – FR-010, FR-014)
- FR-005 Page Capture, Selectors, and Visual Analysis – selectors.json, vision locators, artifact indices.
- FR-006 Requirements Synthesis – clustering, LLM prompting, Markdown/JSON exports.
- FR-007 Test Scenario Derivation – cross-language test generation, static checks.
- FR-008 Artifact Packaging – Azure Blob upload, manifest integrity, retries.
- FR-009 Public API & CLI – run lifecycle, typed clients, pagination, streaming.
- FR-010 Web UI – Lovable UI for run submission, live telemetry, FRD rendering.
- FR-014 Test Execution Orchestrator (optional v1) – sandbox runners, JUnit/trace aggregation.
- **Immediate actions**
  - Extend FR-006 synthesis across additional captured flows using RUN-FR006-009-001 as the template and surface deltas in FRD/export JSON.
  - Automate FR-007/FR-008 pipeline (pytest collect, Maven compile, packaging index, API response capture) so each new run emits ready-to-publish evidence bundles.
  - Partner with Codex agent on CLI/API artifact listing + status streaming to close remaining FR-009 scope.

### Codex Agent – Observability, Safety, CI, Security (FR-011 – FR-013, FR-015 – FR-017) + Automation Backbone
- FR-011 Observability and Telemetry – structured logging, Langfuse integration, dashboards.
- FR-012 Reliability and Recovery – Temporal retries, checkpoints, DLQ strategy.
- FR-013 Multi-tenant Permissions – RBAC, org scoping, artifact isolation.
- FR-015 CI Integrations – reusable workflow YAML, documentation, repo detection.
- FR-016 Safety, Rate Limiting, Guardrails – throttles, destructive-action blocklists, dry-run mode.
- FR-017 Security Controls – secrets management, encryption, audit logging.
- Automation steward for `tools/build_run_summary.py`, `docs/checklist_autoupdate.py`, and observability KPI exports.
- **Immediate actions**
  - Expand `docs/architecture.md`/`docs/deployment.md` stubs with observability + security sections to close FRD TODOs.
  - Build dashboards tracking coverage_percent, story_to_test_coverage, and artifact upload success; expose run IDs for Agents Alpha/Beta.
  - Draft GitHub Actions workflow referencing the new builder/updater for CI hand-off (align with Agent Beta’s FR-009 API).

## Coordination Cadence
- **Daily standup (async)**: post status + blockers in shared channel referencing FR IDs and checklist evidence.
- **Twice-weekly deep dive**: alternate focus between exploration/capture (Alpha+Beta) and observability/safety (Beta+Codex).
- **Evidence management**: all agents publish run summaries + criteria JSON under `artifacts/<date>/<run-id>/` and run `docs/checklist_autoupdate.py` to keep the checklist authoritative.

## Risks & Mitigations
- Selector/test drift between Agents Alpha and Beta → maintain shared schema doc and regression tests triggered by Codex CI workflow.
- Observability gaps delaying verification → Codex agent to prioritize FR-011 instrumentation before Beta’s FR-010 UI work begins.
- Security compliance delays → Codex agent and Agent Alpha share credential-handling checklist before production credential storage is enabled.

## Next Sync Prep
- Agents Alpha & Beta: deliver initial design notes + risk list in new stubs by next working day.
- Codex agent: provide sample dashboard mock and CI workflow draft for review.

Adjust assignments as priorities change; update `docs/rtm_execution_plan_v1.md` owner lines if responsibilities shift.
