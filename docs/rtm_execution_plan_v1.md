# GazeQA RTM Execution Plan

- Version: 2025-09-16 draft
- Generated: 2025-09-16T15:40:29Z UTC
- Source: docs/gaze_qa_rtm_v_4.json, docs/gaze_qa_frd_v_4.md, docs/gaze_qa_test_case_catalog_v_4.json, docs/gaze_qa_checklist_v_4.json

## Done Definition
- Successful login where applicable
- At least 97 percent page coverage across exploration + crawl
- At least 98 percent story-to-test coverage with runnable suites
- All artifacts persisted to Azure Blob with signed access
- Observable end to end runs with diagnostics for every failure

## Delivery Phases
1. Foundation Workflow (FR-001 to FR-005)
2. Generation and Delivery (FR-006 to FR-009)
3. Experience and Reliability (FR-010 to FR-013)
4. Operations, Safety, and Extensions (FR-014 to FR-017)

---

## FR-001 Task Intake and Configuration
- Owner: Agent Alpha
- Status: Completed
- Components: API, CLI, Orchestrator
- Dependencies: none
- Implementation Tasks:
  1. Define CreateRun schema, validation, and defaults covering URL, credentials, budgets, targets, and storage profile
  2. Persist Run entities, emit `run.created`, and start durable workflow with Temporal run id mapping
  3. Expose POST `/runs`, WS status stream, and CLI wrapper `gazeqa runs create`
  4. Instrument metrics/logs for payload validation and workflow start
- Test and Evidence:
  - TC-FR-001-001 Create run with valid payload
  - TC-FR-001-002 Reject invalid CreateRun payload
  - Checklist criteria FR-001-AC-1/2 marked with API response captures
- Risks / Notes: align schema with CLI prompts; maintain backward compatibility for later CLI automation

## FR-002 Authentication and Session Persistence
- Owner: Agent Alpha
- Status: In Progress
- Components: Navigator, Orchestrator, PersistenceIndexer, Security
- Dependencies: FR-001
- Implementation Tasks:
  1. Integrate CUA login flow detection and storage of successful session markers
  2. Encrypt storageState at rest; wire KMS or Vault for secret handling; suppress secret logging
  3. Implement scripted Playwright fallback with 2FA optional callback hooks and evidence capture
  4. Persist session artifacts per run and reuse when allowed
- Test and Evidence:
  - TC-FR-002-001 Login via CUA succeeds and saves storageState
  - TC-FR-002-002 Fallback scripted login used when CUA fails
  - Checklist criteria FR-002-AC-1/2 with screenshots, storageState artifact, and failure trace
- Risks / Notes: coordinate secure secret transport from CLI/API; consider rotating credentials per run

## FR-003 AI-driven Exploration
- Owner: Agent Alpha
- Status: Completed
- Components: Navigator, Orchestrator, Observability
- Dependencies: FR-001, FR-002
- Implementation Tasks:
  1. Implement exploration policy that balances budgets, avoids loops, and records coverage progress
  2. Capture DOM snapshot + screenshot on each visited page and register entries in page map
  3. Integrate dynamic budget adjustments based on coverage heuristics
  4. Emit coverage metrics, visited logs, and failure signals to observability stack
- Test and Evidence:
  - TC-FR-003-001 AI exploration reaches major sections and captures pages
  - Checklist criteria FR-003-AC-1/2 with coverage report and artifact index
- Risks / Notes: need heuristics for dynamic SPAs; ensure loop breaker state survives workflow restarts

## FR-004 Deterministic BFS Crawl
- Owner: Agent Alpha
- Status: In Progress
- Components: Crawler, Navigator, Orchestrator
- Dependencies: FR-003
- Implementation Tasks:
  1. Build BFS crawler seeded by exploration map with depth/time budget controls
  2. De-duplicate pages using content hash and canonical URLs against AI map
  3. Enforce allowlist/denylist rules including automatic skip on logout/destructive routes
  4. Merge crawl output into unified artifacts and coverage metrics
- Test and Evidence:
  - TC-FR-004-001 BFS adds unique pages and skips logout routes
  - Checklist criteria FR-004-AC-1/2 with combined map diff highlights
- Risks / Notes: ensure crawler respects robots/custom policies; share coverage metrics with FR-003

## FR-005 Page Capture, Selectors, and Visual Analysis
- Owner: Agent Beta
- Status: Completed
- Components: Navigator, AnalysisStoryGen, PersistenceIndexer
- Dependencies: FR-003, FR-004
- Implementation Tasks:
  1. Persist screenshots, DOM JSON, selectors.json, and element inventory per page
  2. Implement multi-strategy selector ranking prioritizing stable attributes
  3. Invoke vision-based locator generator for canvas/obfuscated UI with probe validation
  4. Emit pages.jsonl index referencing artifacts and metadata (timestamp, hash, coverage)
- Test and Evidence:
  - TC-FR-005-001 Selector candidates persisted for each page
  - TC-FR-005-002 Vision analysis yields actionable locator for canvas UI
  - Checklist criteria FR-005-AC-1/2 plus probe click recordings
- Risks / Notes: maintain storage efficiency; consider caching selectors for reuse across runs

## FR-006 Requirements Synthesis – Features, Stories, AC
- Owner: Agent Beta
- Status: Completed (RUN-FR006-009-002)
- Latest Evidence: RUN-FR006-009-002 (extended frd exports, story quality review log)
- Components: AnalysisStoryGen, WebUI, PersistenceIndexer
- Dependencies: FR-005
- Implementation Tasks:
  1. Cluster captured pages into feature areas and stable story identifiers
  2. Generate user stories and AC via prompt templates with critique/repair loop
  3. Export Markdown FRD and JSON for RTM linking while preserving IDs
  4. Index synthesized artifacts with traceability metadata (page ids, selectors)
- Test and Evidence:
  - TC-FR-006-001 Synthesis produces features, stories, and AC
  - Checklist criteria FR-006-AC-1/2 with FRD diff review
- Risks / Notes: design prompt evaluation metrics; watch for hallucinated flows

## FR-007 Test Scenario Derivation and Code Generation
- Owner: Agent Beta
- Status: Completed (RUN-FR006-009-002)
- Latest Evidence: RUN-FR006-009-002 (extended pytest collection + Maven compile logs)
- Components: TestGen, PersistenceIndexer
- Dependencies: FR-005, FR-006
- Implementation Tasks:
  1. Map stories and AC to scenario templates covering positive/negative flows
  2. Generate Playwright (Python) and Selenium (Java) suites with shared selectors
  3. Run static validation (`pytest --collect-only`, `mvn compile`) and embed metadata pointers
  4. Persist tests under artifacts/tests with manifest referencing story IDs
- Test and Evidence:
  - TC-FR-007-001 Generate runnable tests without syntax/compile errors
  - Checklist criteria FR-007-AC-1/2 with CI logs proving collection/compile
- Risks / Notes: manage selector drift; plan for language-specific idioms and maintainability

## FR-008 Artifact Packaging and Azure Blob Storage
- Owner: Agent Beta
- Status: Completed (RUN-FR006-009-002)
- Latest Evidence: RUN-FR006-009-002 (selector index + packaging log)
- Components: PersistenceIndexer, Security
- Dependencies: FR-005, FR-006, FR-007
- Implementation Tasks:
  1. Assemble artifact manifest with checksums, sizes, story/test mappings
  2. Upload artifacts to per-run Azure Blob prefix with retry + backoff strategy
  3. Generate signed URLs or SAS tokens respecting expiration policy
  4. Produce artifacts/index.json and update run metadata with download pointers
- Test and Evidence:
  - TC-FR-008-001 Artifacts uploaded and indexed in Azure Blob
  - Checklist criteria FR-008-AC-1/2 with blob storage audit logs
- Risks / Notes: confirm storage account throughput; guard against partial uploads with transactional updates

## FR-009 Public API and CLI
- Owner: Agent Beta
- Status: In Progress
- Latest Evidence: RUN-FR006-009-002 (CLI/API run creation logs)
- Components: API, CLI, Orchestrator
- Dependencies: FR-001, FR-008
- Implementation Tasks:
  1. Implement REST endpoints for run lifecycle, artifact listings, and event streams with pagination
  2. Provide CLI commands for run creation, status watch, and artifact download, including auth prompts
  3. Publish OpenAPI schema and generate typed clients for Python/TypeScript
  4. Document API usage in docs and integrate with auth/authorization layers
- Test and Evidence:
  - TC-FR-009-001 CI can start a run via API and poll status
  - Checklist criteria FR-009-AC-1/2 with API/CLI session logs
- Risks / Notes: handle rate limiting; ensure CLI gracefully handles partial runs and retries

## FR-010 Web UI
- Owner: Agent Beta
- Status: Planned
- Components: WebUI, API, PersistenceIndexer
- Dependencies: FR-001, FR-006, FR-008
- Implementation Tasks:
  1. Build Lovable-based UI for run submission with validation and stored profiles
  2. Stream live logs, screenshots, and step status using WS/event endpoints
  3. Render FRD Markdown and provide artifact download controls with auth checks
  4. Apply basic WCAG AA support including keyboard navigation and contrast
- Test and Evidence:
  - TC-FR-010-001 Web UI shows live logs and exposes FRD download
  - Checklist criteria FR-010-AC-1/2 with UX recording and accessibility spot checks
- Risks / Notes: ensure UI scales for long runs; plan for latency on artifact loads

## FR-011 Observability and Telemetry
- Owner: Codex agent
- Status: Planned
- Components: Observability, Orchestrator
- Dependencies: FR-001
- Implementation Tasks:
  1. Centralize structured logging with run id correlation and error tagging
  2. Emit metrics (coverage, step durations, retries) to monitoring system with dashboards
  3. Integrate Langfuse for LLM spans and capture prompt/response metadata
  4. Link Temporal workflow history to run ids and expose via UI/API
- Test and Evidence:
  - TC-FR-011-001 LLM spans and failures are observable in Langfuse and logs
  - Checklist criteria FR-011-AC-1/2 with screenshot of dashboards and log extracts
- Risks / Notes: monitor token costs; maintain PII scrubbers in logging pipeline

## FR-012 Reliability and Recovery (Temporal)
- Owner: Codex agent
- Status: Planned
- Components: Orchestrator
- Dependencies: FR-001
- Implementation Tasks:
  1. Configure Temporal retry policies with backoff for critical activities
  2. Implement idempotent checkpoints per phase (intake, login, explore, crawl, synthesis, generation)
  3. Handle browser crash recovery by persisting session/context state and safe relaunch
  4. Route unrecoverable failures to DLQ with alerting and diagnostic bundle
- Test and Evidence:
  - TC-FR-012-001 Workflow resumes after browser crash
  - Checklist criteria FR-012-AC-1/2 with replay logs and checkpoint artifacts
- Risks / Notes: ensure checkpoint data does not leak secrets; quantify recovery times for SLAs

## FR-013 Multi tenant Permissions and Isolation
- Owner: Codex agent
- Status: Planned
- Components: Security, API, WebUI, PersistenceIndexer
- Dependencies: FR-008, FR-009, FR-010
- Implementation Tasks:
  1. Introduce organization scoping in data model and enforce on all queries and storage paths
  2. Implement RBAC roles (submitter, viewer, admin) with policy checks on UI/API
  3. Ensure artifact storage uses per-org prefixes with access control enforced via SAS or signed URLs
  4. Capture audit logs for access attempts and integrate with observability dashboards
- Test and Evidence:
  - TC-FR-013-001 Org isolation and RBAC enforcement
  - Checklist criteria FR-013-AC-1/2 with audit log excerpts
- Risks / Notes: plan migration of existing runs into org structure; consider future billing segmentation

## FR-014 Test Execution Orchestrator (optional v1)
- Owner: Agent Beta
- Status: Planned
- Components: ExecOrchestrator, Observability, PersistenceIndexer
- Dependencies: FR-007
- Implementation Tasks:
  1. Spin up sandboxed runners (containerized) for generated suites with resource caps
  2. Execute Playwright/Selenium suites, collect JUnit XML, traces, and attach to run artifacts
  3. Aggregate execution metrics and publish summary.json plus trend dashboards
  4. Expose execution status via API/UI and clean up environments
- Test and Evidence:
  - TC-FR-014-001 Execute generated tests and collect JUnit results
  - Checklist criteria FR-014-AC-1/2 with trace viewer references
- Risks / Notes: optional for v1; consider asynchronous execution billing

## FR-015 CI Integrations (GitHub Actions when available)
- Owner: Codex agent
- Status: Planned
- Components: CI, API, PersistenceIndexer
- Dependencies: FR-007, FR-008, FR-009
- Implementation Tasks:
  1. Provide reusable workflow YAML with secrets management guidance and failure notifications
  2. Detect repo access to toggle auto-provision vs manual CLI instructions
  3. Publish documentation and examples for GitHub Actions plus alternative CI scripts
  4. Validate artifact publication and run creation when triggered by CI events
- Test and Evidence:
  - TC-FR-015-001 GitHub Action triggers analysis and publishes artifacts
  - Checklist criteria FR-015-AC-1/2 with workflow logs and artifact listing
- Risks / Notes: handle rate limits for CI; maintain compatibility as API evolves

## FR-016 Safety, Rate Limiting, and Guardrails
- Owner: Codex agent
- Status: Planned
- Components: Security, Orchestrator, Navigator, Crawler
- Dependencies: FR-003, FR-004
- Implementation Tasks:
  1. Enforce global and per-domain rate limits with configurable caps and metrics
  2. Maintain blocklists for destructive UI actions (Delete, Wipe, Reset) with override via sandbox mode
  3. Provide dry-run mode for read-only exploration with explicit warnings
  4. Log guardrail decisions and expose in observability dashboards for audits
- Test and Evidence:
  - TC-FR-016-001 Rate limits enforced during crawl and exploration
  - TC-FR-016-002 Avoid destructive UI by default
  - Checklist criteria FR-016-AC-1/2 with throttle logs and blocklist outputs
- Risks / Notes: coordinate with target app owners about acceptable automation footprint

## FR-017 Security Controls
- Owner: Codex agent
- Status: Planned
- Components: Security, PersistenceIndexer, API
- Dependencies: FR-008, FR-009
- Implementation Tasks:
  1. Centralize secret access via vault/KMS, ensure TLS for all internal and external endpoints
  2. Encrypt sensitive artifacts at rest and manage key rotation schedules
  3. Redact secrets from logs and monitors, enforce least privilege across services
  4. Provide audit trail for artifact download and privileged actions with alerting on anomalies
- Test and Evidence:
  - TC-FR-017-001 Secrets not logged and SAS links are time bound
  - Checklist criteria FR-017-AC-1/2 with audit log verification and SAS expiry tests
- Risks / Notes: schedule periodic security review; plan for compliance certifications

---

## Operational Tracking
- Update docs/gaze_qa_checklist_v_4.json after each verification run with evidence bundle paths
- Capture run ids and artifact locations in observability dashboards for traceability
- Maintain weekly status review to unblock dependencies and monitor Done Definition metrics
- Track Done Definition KPIs explicitly: coverage_percent from FR-003/004 pipelines, story_to_test_coverage from FR-007 output manifests, and artifact upload success from FR-008 logs
- Alert on regressions when coverage or verification metrics fall below thresholds

## Next Steps
1. Assign engineering owners and target completion dates per FR
2. Stand up shared dashboard tracking RTM progress, checklist pass rate, and Done Definition KPIs
3. Integrate automated test execution into CI to continuously validate RTM coverage