# GazeQA Architecture Overview (Stub)

> Working draft owned by Agent Alpha. Focus is FR-001 Task Intake and Configuration and FR-002 Authentication and Session Persistence. Expand as discovery progresses; link back to FRD/RTM rows when sections are promoted to final.

## 1. Purpose & Scope
- Capture the initial system view required for intake/auth discovery and unblock downstream design references.
- Summarize current assumptions, integration points, and risks for FR-001 and FR-002.
- Track open questions and discovery tasks that must be resolved before implementation OKRs lock.

## 2. System Context (Current Assumptions)
- **Control plane**: REST API (`POST /runs`, `GET /runs/{id}`, `GET /runs/{id}/artifacts`), CLI wrapper (`gazeqa runs create`), future Lovable UI. All entry points share the same CreateRun schema.
- **Orchestration**: Temporal workflow per run. Temporal `workflowId` matches `run.id`; activities span intake validation, auth, exploration, crawl, synthesis.
- **Execution surfaces**: Browserbase session for CUA-first auth/exploration; Playwright workers for scripted fallbacks and deterministic capture.
- **State & Artifacts**: Azure Blob Storage for run artifacts (JSON indices, screenshots, session storageState). Optional Postgres table for run metadata and checklist evidence.
- **Secrets management**: Envelope encryption via platform KMS (TBD provider). Secrets never logged; at-rest encryption mandatory for credentials + storageState.
- **Observability**: Metrics (`runs_created_total`, `login_success_rate`), traces (intake span, auth attempts), structured logs with redaction pipeline.

## 3. Core Data Models (Draft)
- **Run**
  - `id`, `created_at`, `status`, `status_reason?`, `params` (JSONB), `config_version`, `payload_hash`, `metrics` (JSONB), `initiator` (CLI vs API key), `last_updated_at`.
  - Indexes on `status`, `created_at`, `initiator`, `payload_hash` for idempotency lookups.
- **RunEvent** (optional audit trail)
  - `run_id`, `timestamp`, `type` (`run.created`, `status.changed`, `auth.success`, ...), `details` (JSON), `emitter` (service ID).
- **SessionArtifact**
  - `run_id`, `method`, `created_at`, `browser_provider`, `storage_state_blob`, `ttl_minutes`, `fallback_attempted`, `evidence_manifest`, `encryption_key_id`.
- **CredentialReference**
  - `secret_ref`, `issued_at`, `issued_by`, `run_id?`, `ttl_minutes`, `scopes` (allowed domains/actions), `status` (`active`, `revoked`).
- **EvidenceManifest**
  - `run_id`, `phase` (`intake`, `auth`), `version`, `artifacts[]` (path, type, visibility, trace_id, sha256), `generated_at`, `checksum`.

## 4. FR-001 Task Intake and Configuration
### 5.1 Flow Summary
1. Entry point receives CreateRun payload (API/CLI/UI).
2. Validate payload (URL reachability optional, schema required fields, budget limits, feature toggles).
3. Persist `Run` record (`id`, `created_at`, `params`, `status=Pending`, `metrics{}`).
4. Emit `run.created` event and start Temporal workflow.
5. Respond with run id + initial status; stream updates over WS (later) / CLI polling.

### 4.2 Key Components & Interfaces
- `RunService` – validation + persistence + workflow kickoff.
- `RunRepository` – writes to Postgres; ensures idempotent `CreateRun` by payload hash.
- `WorkflowClient` – maps run id to Temporal `workflowId`, injects initial params.
- `EventBus` – publishes `run.created`, `run.completed` (Kafka/SNS TBD).
- CLI command `gazeqa runs create` – prompts for missing fields, handles credential entry via secure prompt.

### 4.3 CreateRun Payload (draft)
```json
{
  "target_url": "https://example-app.test",
  "credentials": {
    "username": "user@example.com",
    "secret_ref": "vault://kv/gazeqa/runs/123"  
  },
  "framework_targets": ["pytest", "junit"],
  "budgets": {
    "explore_minutes": 12,
    "crawl_minutes": 8,
    "max_pages": 180
  },
  "proxy_profile": "default",
  "browser_provider": "browserbase",
  "storage_profile": "azure-blob-standard",
  "flags": {
    "allow_public_runs": false,
    "reuse_storage_state": true
  }
}
```
- Credentials captured via secure prompt; API variant expects opaque `secret_ref` (no raw secret transit).
- `flags` default from server config; CLI shows defaults but defers to server truth.

### 4.4 Observability & Controls
- Validation metrics (`runs_rejected_total` by reason), intake latency histogram, payload schema version tags.
- Structured audit log storing request metadata minus secrets.
- Circuit breaker for workflow start failures (`workflow_start_error_rate`).

### 4.5 Open Questions / Risks
- Confirm KMS provider (Azure Key Vault vs AWS KMS) and API for issuing `secret_ref`.
- Decide on schema versioning strategy (`payload_version`, migrations for persisted params).
- Determine CLI offline mode: can CLI stage payload and submit later?
- Clarify Browserbase toggle semantics (`browser_provider` vs boolean flag); align with orchestrator expectations.
- Identify source of default budgets and enforcement (server config vs run template library).

### 4.6 Run Status Lifecycle (assumptions)
- `Pending` – set immediately after persistence; waiting for Temporal workflow handshake.
- `Initializing` – optional intermediate once workflow starts but before auth kicks off; gives operators signal that orchestration is healthy.
- `Authenticating` – active while FR-002 flow is establishing a session.
- `Exploring` / `Crawling` / `Synthesizing` – downstream phases reported via workflow heartbeats; not owned by FR-001 but surfaced for status UX continuity.
- `Completed` / `Failed` / `Cancelled` – terminal states; FR-001 owns persistence of final status and summary metadata.

### 4.7 External Dependencies & Contracts
- Temporal Cloud/cluster: workflow start API, search attributes for `run.id` lookup.
- Message bus (`run.created`): candidate providers Kafka vs SNS/SQS; schema versioned envelope, payload hashed for integrity.
- Secrets service: must accept `run.id`, `payload_hash`, and return opaque `secret_ref` for storage.
- Browser provider registry: maps `browser_provider` flag to concrete executor (Browserbase, local Playwright, future vendors).
- Audit log sink: structured log aggregator with field redaction (e.g., Datadog, Splunk).

### 4.8 CLI ↔ API Interaction Notes
- CLI should sanitize local logs (no secrets, redact URLs if marked sensitive) and respect `payload_version` announced by API.
- Interactive credential capture flows: CLI prompts store secrets in memory only; POST payload contains `secret_ref_request` that API resolves via SecretsBroker.
- Non-interactive/CI mode: CLI accepts `--secret-ref` flag to reuse pre-provisioned credentials; validation ensures server confirms ownership.
- Retry semantics: CLI retries transient 5xx once, but surfaces validation errors immediately with field-level hints pulled from API response.
- Evidence bootstrap: CLI can optionally upload pre-run context (e.g., credentials verification screenshot) to align with `runs/<run-id>/intake/` layout.

### 4.9 Failure Modes & Mitigations
- **Schema drift** – mitigate with versioned payloads and compatibility contract tests; CLI fetches schema metadata before submission.
- **Temporal workflow start failure** – catch exceptions, mark run `Failed (intake_workflow_start)`, emit alert, retry start up to 3x with exponential backoff.
- **SecretsBroker outage** – hold request in Pending with `status_reason`, enqueue retry job, notify operator if unresolved within 5 minutes.
- **Message bus publish failure** – buffer `run.created` in durable queue; re-drain on recovery to keep downstream consumers consistent.
- **Double submission** – enforce idempotency key derived from payload hash; respond with existing run reference instead of creating duplicates.

## 5. FR-002 Authentication & Session Persistence
### 4.1 Flow Summary
1. Intake passes authenticated target metadata + credentials reference to auth activity.
2. Auth activity requests session from Browserbase via CUA:
   - Initiate CUA run, feed login goal, await post-login signal (DOM marker or redirect).
3. If CUA fails or times out, trigger Playwright scripted fallback (selectors from knowledge base or prompt-generated script).
4. Upon success, capture Playwright `storageState`, Browserbase session id/context, metadata (timestamp, login method).
5. Encrypt and persist session artifact to Blob + metadata row (`SessionArtifact`). Emit `auth.success`.
6. On failure after retries, emit `auth.failed` with evidence (screenshots, console logs).

### 5.2 Components & Interfaces
- `AuthOrchestrator` Temporal activity orchestrating CUA and fallback attempts.
- `CUAExecutor` bridging Responses API tool calls to Browserbase session.
- `FallbackLoginRunner` running Playwright script with typed selectors / instructions.
- `SecretsBroker` resolving `secret_ref` to plaintext credentials within secure enclave (never persisted unencrypted).
- `SessionVault` handling encryption and Blob upload, returning artifact pointer to workflow state.

### 5.3 Session Artifact Schema (draft)
```json
{
  "run_id": "run_2025_09_16_0012",
  "method": "cua",
  "created_at": "2025-09-16T15:54:00Z",
  "browser_provider": "browserbase",
  "storage_state_blob": "blob://runs/run_2025_09_16_0012/session/storageState.json.enc",
  "session_ttl_minutes": 90,
  "evidence": [
    "blob://runs/run_2025_09_16_0012/session/login_screenshot.png"
  ],
  "fallback_attempted": false,
  "metadata": {
    "login_indicator_selector": "#dashboard",
    "retries": 1
  }
}
```
- Encryption: envelope key stored in KMS; per-artifact data key rotated per run.
- Evidence stored alongside for debugging; flagged for redaction if UI shows PII.

### 5.4 Observability & Controls
- Metrics: `login_success_rate`, `login_time_seconds` (with method dimension), `auth_fallback_used_total`.
- Logs: redact usernames; attach run id, method, retry count.
- Traces: child span per auth attempt; annotate with Browserbase session id (hashed).
- Alerts: page for sustained auth failure rate > 20 percent over 15 minutes.

### 5.5 Open Questions / Risks
- Define reliable success indicator library (DOM selectors, URL patterns) per target domain.
- Need policy for credential updates/rotation during long-lived projects.
- Clarify storage location + retention for encrypted storageState (Blob vs secure DB) and purge schedule.
- Establish 2FA handling: human-in-the-loop vs automated TOTP integration? (Acceptance criteria allows optional callback.)
- Determine how auth evidence is shared with downstream agents without leaking secrets (viewer roles, masked screenshots).

### 5.6 Decision Matrix – CUA vs Fallback
| Condition | Primary path | Timeout budget | Escalation |
|-----------|--------------|----------------|------------|
| Known login form, low risk | CUA | 90s wall clock, 12 actions | Retry once then mark partial |
| Dynamic form, prior heuristics available | Playwright fallback | 60s, scripted waits per selector | Capture HAR + screenshot, escalate to human |
| 2FA required | CUA + callback | 2 attempts, gated prompt | Notify operator, await manual token |
| Repeated credential failure | Abort | n/a | Emit `auth.failed`, trigger incident |

### 5.7 Interface Contracts
- **`AuthRequest` payload (from workflow)**: `run_id`, `target_url`, `secret_ref`, `success_markers[]`, `fallback_script_id?`.
- **`AuthResult` (to workflow)**: `status` (`success|partial|failed`), `method` (`cua|fallback`), `storage_state_pointer`, `evidence[]`, `duration_ms`, `retries`.
- **SecretsBroker API**: `ResolveSecret(secret_ref, purpose)` → ephemeral credentials (+ audit record with TTL).
- **SessionVault API**: `Put(run_id, artifact)` → blob URI; `Get(run_id)` returns decrypted session for internal reuse with strict scoping.
- **Evidence pipeline**: push screenshots/logs to blob with redaction tags so Codex observability agent can mask before sharing.

### 5.8 Evidence Handling Framework
- Evidence bundle naming: `runs/<run-id>/auth/<timestamp>-<step>-<type>.{png,json,log}` with manifest for quick lookup.
- Redaction policy: apply automated blur/mask for detected email/password fields before sharing with downstream teams; store unredacted originals under restricted container for incident response only.
- Checklist integration: `AuthResult.evidence[]` should include signed URL pointers and metadata (step name, visibility level). Agents update checklist via `docs/checklist_autoupdate.py` hooking into manifest.
- Observability cross-link: emit trace IDs in evidence metadata so dashboards link to screenshots/logs.
- Retention: default 30 days; purge job ensures encrypted evidence rotates; exceptions require security approval.

### 5.9 Error Taxonomy & Retry Strategy
- **Transient navigation failures** – retry CUA actions with adaptive waits; cap at 2 cycles before falling back to scripted login.
- **Credential rejection** – immediately halt automated retries after 2 failures; escalate to human review to avoid lockouts.
- **Browserbase session interruptions** – attempt session resume if within TTL; otherwise restart auth flow with new session context.
- **Playwright fallback script errors** – capture console/HAR, increment script failure metric, and mark script as suspect for review.
- **SecretsBroker resolve failure mid-run** – abort auth, set run status `Failed (secret_resolve)`, attach evidence and diagnostic logs.

## 6. Cross-Cutting Considerations
- **Configuration hierarchy**: environment defaults (`.env.template`) → server config → run overrides. Document precedence once config service is implemented.
- **Config discovery**: expose read-only `/config/intake` endpoint so CLI/UI can preview effective defaults; include `config_version` in run metadata for reproducibility.
- **Secure toggles**: auth-related flags (`auth.allow_storage_state_reuse`, provider feature availability) live in a protected config store; workflow receives a signed snapshot at start.
- **Error handling**: temporal retries for transient errors; escalate to manual review after N retries with evidence.
- **Compliance/Security**: align with FR-017 controls—least-privileged access to SecretsBroker, per-run data-key rotation, tamper-evident audit logging, and evidence redaction safeguards.
- **Collaboration hooks**: provide schema exports for Agent Beta (selector expectations) and Codex agent (observability wiring) once finalized.
- **Access control**: run-level RBAC (owner, collaborator, viewer) determines who can view intake/auth evidence and trigger re-runs; integrate with multi-tenant permissions model.

## 7. Discovery Todo List
- [ ] Validate CreateRun schema with CLI UX design; refactor payload sample once fields finalize.
- [ ] Prototype secret reference flow end-to-end (CLI prompt → API → SecretsBroker).
- [ ] Spike Browserbase + CUA login for two sample apps to document success indicators + evidence capture.
- [ ] Draft encryption/decryption module API for SessionVault (coordinate with Security team).
- [ ] Document fallback script packaging + versioning (where stored, how updated, how selected per domain).
- [ ] Align evidence manifest format with Codex observability dashboards and checklist updater expectations.
- [ ] Define run status event schema (`run.status.changed`) and integrate with CLI streaming UX.
- [ ] Confirm retention + purge policy SLAs with Security (map to FR-017 controls).
- [ ] Draft error taxonomy playbook linking failure codes to alerting/response steps.
- [ ] Prototype idempotency key derivation shared by CLI/API to guard against duplicate submissions.

## 8. Sequence & Diagram Backlog
- [ ] Intake happy-path sequence: CLI/UI → API → RunService → Temporal workflow → status callback.
- [ ] Auth success/failure branches: Workflow → AuthOrchestrator → CUAExecutor/Browserbase → SessionVault.
- [ ] Data flow diagram showing secrets lifecycle from CLI prompt to encrypted storage.
- [ ] State diagram for run status transitions shared with FR-003/FR-004 owners.

## 9. Dependency & Alignment Notes
- FR-003 requires authenticated context metadata to include session TTL and evidence pointers; ensure schema aligns before exploration MVP.
- FR-004 depends on Run status events to know when to begin BFS; maintain consistent event naming.
- Codex observability (FR-011) needs metrics namespace agreements (`gazeqa.intake.*`, `gazeqa.auth.*`).
- Security (FR-017) will own KMS integration; intake/auth must not diverge from central policy.
- Checklist automation expects evidence bundle URIs in predictable blob prefixes (`runs/<run-id>/intake/*`, `runs/<run-id>/auth/*`).

> Next update: integrate findings from intake schema validation workshop and publish rev1 with sequence diagrams.

## 10. Checklist & Evidence Workflow
- Intake/auth runs produce manifest JSON (`runs/<run-id>/intake/manifest.json`) summarizing evidence artifacts with classifications (internal, sharable, restricted).
- Checklist updater consumes manifest plus run metadata to populate `docs/gaze_qa_checklist_v_4.json` entries `FR-001-AC-*` and `FR-002-AC-*` automatically.
- Manual review path: if evidence flagged `restricted`, require security approval before checklist marks AC as passed; tool should support pending status.
- Store checklist sync logs alongside manifest for audit (`runs/<run-id>/intake/checklist-sync.log`).
- Provide CLI shim `gazeqa runs evidence sync <run-id>` that wraps manifest generation and checklist updater invocation to keep process reproducible.

## 11. Implementation Sequencing (Draft)
1. **Schema & Config Foundations**
   - Finalize CreateRun payload, config discovery endpoint, idempotency key mechanics.
   - Establish SecretsBroker contract and stubbed integration tests.
2. **Workflow Bootstrap**
   - Implement RunService + Temporal kickoff with status lifecycle + event publishing.
   - Wire basic metrics/logging for intake success/failure paths.
3. **Auth Orchestration MVP**
   - Integrate CUA executor with minimal success detection + evidence capture.
   - Persist SessionArtifact with encryption wrappers; provide manifest skeleton.
4. **Fallback + Evidence Hardening**
   - Add Playwright fallback runner, decision matrix enforcement, redaction pipeline, and retry policies.
   - Automate checklist updater hook using manifest outputs.
5. **Operationalization**
   - Implement run-level RBAC checks, retention/purge jobs, and alerting rules mapped to error taxonomy.
   - Deliver dashboards + CLI enhancements (status streaming, evidence sync command).
6. **Discovery Close-Out**
   - Produce sequence/state diagrams, finalize documentation, and sign off with Security/Observability stakeholders.

### 3.4 Prototype Implementation Notes (2025-09-16)
- `gazeqa.run_service.RunService` persists runs locally under `artifacts/runs/` and emits a minimal `run_manifest.json` + `run_summary.json` for downstream tooling.
- `gazeqa.models.CreateRunPayload` validates schema fields (URL, credentials, budgets, storage profile, tags) and raises `ValidationError` with field-specific errors.
- CLI entry point `python -m gazeqa.cli <payload.json>` or `gazeqa-cli <payload.json>` exercises FR-001 acceptance criteria locally.
- Unit tests under `tests/test_run_service.py` verify success and invalid payload behaviour.

## 4. API Prototype (FR-001 scope)
- Module `gazeqa.api` exposes a minimal HTTP server providing `POST /runs`.
- Uses Python `http.server.ThreadingHTTPServer`; payload validation delegated to `CreateRunPayload`.
- Successful requests return `201` with run manifest JSON; validation errors return `400` with `field_errors`.
- Start locally with `python -m gazeqa.api` (listens on 127.0.0.1:8000).
- CI/TDD support via `tests/test_api.py` exercising the endpoint end-to-end.

## 5. Authentication Prototype (FR-002)
- `gazeqa.auth.AuthenticationOrchestrator` models the CUA-first then fallback flow, persisting `storageState.json.enc` and `auth_result.json` under each run.
- CLI (`gazeqa.cli`) and API (`gazeqa.api`) now bootstrap the orchestrator automatically when `GAZEQA_AUTH_ENCRYPTION_KEY` is present, wiring Browserbase CUA + Playwright fallback callables with environment-sourced config.
- Configurable via `AuthConfig` (storage root, timeout, fallback toggle, selectors, provider metadata).
- Evidence storage aligns with FR-002 acceptance criteria (success path saves storage state, failure surfaces stage).

## 6. Exploration Prototype (FR-003)
- `gazeqa.exploration.ExplorationEngine` simulates coverage-based traversal, emitting `coverage_report.json`, `visited_pages.jsonl`, and `skipped_pages.jsonl`.
- Coverage threshold defaults to 80 percent; configurable via `ExplorationConfig`.
- Artifacts stored under `artifacts/runs/<RUN-ID>/exploration/` to align with TC-FR-003-001 evidence.
- Unit test `tests/test_exploration.py` verifies persistence and coverage calculation.

## 7. BFS Crawl Prototype (FR-004)
- `gazeqa.bfs.BFSCrawler` traverses an in-memory link graph, persisting `bfs/page_map.jsonl`, `bfs/skipped_links.json`, and `bfs/coverage_merge.json` for each run.
- `CrawlConfig` supports depth caps and keyword skips (e.g., logout/destructive links) so criteria for exclusion rules can be validated.
- Unit test `tests/test_bfs.py` confirms persistence and skip logic.
- Combine with exploration artifacts to hit FR-004 acceptance criteria (TC-FR-004-001).
