# Functional Requirements Document (FRD)

> Purpose: a concise, complete, machine-parseable FRD for AI orchestrators and coding agents. Prose is crisp. IDs are stable and traceable.

---

## 0. Document Info
- Project name: GazeQA – Autonomous Requirements and Test Generation for Web Apps
- Version: 1.0.0
- Date: 2025-09-16 (Asia/Manila)
- Source of truth repo or folder: to be created – `gazeqa-platform` (proposed) with `docs/` for artifacts
- Related artifacts
  - RTM JSON path: `docs/rtm.json`
  - Checklist JSON path: `docs/checklist.json`
  - Design docs: `docs/architecture.md`, `docs/agents.md`, `docs/deployment.md`
  - API schema links: `docs/api/openapi.yaml`

---

## 1. Executive Summary
GazeQA discovers what a web app does, writes the requirements, and generates executable tests automatically. It drives a browser with AI to map pages and flows, clusters functionality into features, produces user stories with acceptance criteria, and renders PyTest+Playwright and JUnit+Selenium scripts. Outputs, logs, screenshots, and code are persisted to Azure Blob and indexed for retrieval. Done means: successful login where applicable, ≥97 percent page coverage, ≥98 percent story-to-test coverage, artifacts saved, and runs observable end to end.

- Business value
  - Compress weeks of manual QA and documentation into hours while increasing coverage and traceability.
  - Create a repeatable, auditable pipeline that ties requirements to tests for continuous delivery.

---

## 2. Goals and Non-Goals
- Goals
  - G1: Autonomously explore authenticated web apps and generate an FRD with user stories and AC.
  - G2: Generate runnable test suites in PyTest+Playwright and JUnit+Selenium with traceability.
  - G3: Persist artifacts to Azure Blob with an index and expose them via UI, CLI, and API.
  - G4: Provide robust observability, retries, and recovery for long-running agent workflows.
- Non-goals
  - NG1: Mobile native app automation in v1 (web only). 
  - NG2: Human security review of target apps. The platform assumes authorized use by the customer.

---

## 3. Scope
- In scope
  - AI-driven exploration using OpenAI Computer Use and Playwright.
  - Deterministic BFS crawl with Crawlee to complement AI coverage.
  - Visual analysis of screenshots for non-standard DOMs; robust selector generation with optional DOM instrumentation.
  - Requirements synthesis, user stories, AC, test scenarios, and test code generation.
  - Optional scripted login fallback and session reuse via Playwright storageState.
  - Artifact storage in Azure Blob and JSON index; REST API, CLI, and Lovable-based web UI.
  - Orchestration with Temporal, telemetry with Langfuse.
- Out of scope
  - Solving hard CAPTCHAs or hardware-token 2FA. 
  - Native mobile gestures or desktop-only applications.
- Interfaces in scope
  - OpenAI APIs (GPT-5-mini, computer-use-preview), Browserbase cloud browsers, Azure Blob, Temporal, Langfuse, Crawlee, Playwright, Selenium.
- Interfaces out of scope
  - Payment processing, licensing, and billing.

---

## 4. Personas and Key Use Cases
- QA Lead: needs rapid coverage, traceability, and downloadable tests. Success: high coverage and passing CI runs.
- Fractional CTO/Engineer: needs CI-ready artifacts and API control. Success: pipeline integration in a day.
- Product Owner: wants readable FRD and status visibility. Success: clear stories with AC mapped to tests.

- Top use cases
  - UC1: “Generate FRD and tests for my staging app.” Steps: submit URL+creds → AI login → explore+crawl → synthesize FRD → generate tests → upload artifacts. Success: artifacts indexed and downloadable; coverage meets targets.
  - UC2: “Re-run after a release.” Steps: pick prior config → reuse session where safe → delta-explore → regenerate changed stories/tests → version and store. Success: diffs visible; new tests pass locally.

---

## 5. System Context and Architecture Overview
- Context
  - External systems: OpenAI, Browserbase, Azure Blob, Temporal, Langfuse.
  - Flow: Task created → login → AI explore + BFS crawl → page map → requirements → tests → artifacts persisted → results served via API/UI/CLI.
- High-level components
  - Orchestrator (Temporal Workflow): coordinates phases and durability.
  - Navigator (Playwright + CUA): acts in the browser, collects DOM and screenshots.
  - Crawler (Crawlee): BFS traversal with guardrails.
  - Analysis & Story Generator (LLM): features, stories, AC.
  - Test Generator (LLM): scenarios and code for PyTest and JUnit.
  - Persistence & Indexer: Azure Blob + JSON index; optional Postgres for metadata.
  - API + CLI + Lovable UI: control plane and artifact access.
- Operational constraints
  - Single-region to start; data residency configurable via Blob account. Uptime target 99.5 percent. Cost caps via rate limits and concurrency settings.

---

## 6. Functional Requirements

### FR-001 Task Intake and Configuration
- Type: feature
- Priority: MUST
- Rationale
  - Establish a consistent entry point with reproducible parameters.
- Description
  - Create, validate, and persist a run with inputs: URL, optional credentials, framework targets, depth/time budgets, proxy, Browserbase toggle, and storage profile.
- Inputs and outputs
  - Inputs: JSON payload via API or UI form.
  - Outputs: run id, status stream, artifact index on completion.
- Preconditions
  - Valid API keys configured server-side.
- Postconditions
  - Run created with durable workflow instance started.
- Happy path
  - Create run → return id → orchestrator starts.
- Alternative and error paths
  - Validation errors → 400; provider keys missing → 503 with actionable message.
- API surface changes
  - POST /runs, GET /runs/{id}, GET /runs/{id}/artifacts
- Data model changes
  - Entity Run(id, created_at, params, status, metrics)
- Events and queues
  - `run.created`, `run.completed`
- Observability
  - Metrics: runs_created_total; Logs: params hash; Traces: intake span.
- Security and privacy
  - Secrets never echoed; creds encrypted in transit and at rest if stored.
- Feature flags and config
  - `intake.allow_public_runs` default false.
- Acceptance criteria
  - Given a valid payload, when POST /runs is called, then a run id is returned and status is Pending.
  - Given an invalid payload, when POST /runs, then a 400 with field errors is returned.
- Traceability hooks
  - RTM.id: FR-001
  - Checklist.criteria: mirrors ACs

### FR-002 Authentication and Session Persistence
- Type: feature
- Priority: MUST
- Rationale
  - Access authenticated areas reliably with minimal human input.
- Description
  - Attempt CUA-driven login in Browserbase; on failure, use scripted Playwright fallback. Persist session using Playwright storageState and, where supported, Browserbase session context.
- Inputs and outputs
  - Inputs: login URL or discovery, username, secret, optional 2FA hook.
  - Outputs: authenticated browser context, storageState JSON.
- Preconditions
  - Valid credentials; target app reachable.
- Postconditions
  - Authenticated session reusable by explorer and crawler.
- Happy path
  - CUA identifies form, submits, lands on post-login page.
- Alternative and error paths
  - 2FA encountered → prompt or mark partial; repeated failures → abort with screenshot.
- API surface
  - none external; internal activities only.
- Data model changes
  - SessionArtifact(run_id, path, created_at)
- Events
  - `auth.success`, `auth.fallback_used`, `auth.failed`
- Observability
  - Login success rate; time_to_login p95.
- Security and privacy
  - Do not log secrets; storageState encrypted at rest.
- Feature flags and config
  - `auth.allow_storage_state_reuse` default true; TTL per run.
- Acceptance criteria
  - Given valid credentials, when login is attempted, then post-login indicator is detected within timeout.
  - Given failure on CUA, when fallback runs, then login succeeds or failure is surfaced with evidence.
- Traceability hooks
  - RTM.id: FR-002

### FR-003 AI-driven Exploration
- Type: feature
- Priority: MUST
- Rationale
  - Discover flows that a static crawler might miss.
- Description
  - Use CUA to reason over the current page and choose next actions; collect page metadata, DOM, and screenshots; avoid destructive actions via rules.
- Inputs and outputs
  - Inputs: authenticated context, exploration budget.
  - Outputs: list of visited states, transitions, artifacts.
- Preconditions
  - FR-002 success or public app.
- Postconditions
  - Page map with coverage metrics.
- Happy path
  - Identify nav hubs → visit child pages → record artifacts.
- Alternative and error paths
  - Stuck loops → breaker trips; spinner timeout → reload then skip.
- Events
  - `page.visited`, `explore.loop_break`
- Observability
  - pages_visited_total; actions_per_page p50/p95.
- Security and privacy
  - Blocklists for destructive labels (Delete, Wipe, Reset) unless sandbox enabled.
- Feature flags
  - `explore.allow_form_submit` default limited with dummy data only.
- Acceptance criteria
  - Given a typical SPA, when exploration runs, then ≥80 percent of top-level sections are reached within budget.
  - Given instrumented logging, when exploration completes, then each visited page has a screenshot and DOM snapshot.
- Traceability hooks
  - RTM.id: FR-003

### FR-004 Deterministic BFS Crawl
- Type: feature
- Priority: MUST
- Rationale
  - Ensure structured coverage and complement AI paths.
- Description
  - BFS through reachable internal links with rules to avoid logout and destructive endpoints; de-duplicate against AI map.
- Inputs and outputs
  - Inputs: seeds, exclusion rules.
  - Outputs: additional pages and artifacts.
- Preconditions
  - Session established when required.
- Postconditions
  - Combined coverage meets target.
- Acceptance criteria
  - Given a site with deep links, when BFS runs, then newly discovered pages are appended and de-duplicated.
  - Given exclusion rules, when encountering logout links, then they are skipped.
- Traceability hooks
  - RTM.id: FR-004

### FR-005 Page Capture, Selectors, and Visual Analysis
- Type: feature
- Priority: MUST
- Rationale
  - Reliable assertions need robust selectors and ground truth.
- Description
  - Persist screenshots, DOM snapshots, semantic element inventory; generate stable selectors; invoke vision model for canvas or obfuscated UIs; optional DOM instrumentation to inject stable data attributes in memory for selection.
- Inputs and outputs
  - Inputs: page context, capture policy.
  - Outputs: `pages.jsonl`, screenshots, selectors.json.
- Acceptance criteria
  - Given a page, when captured, then a screenshot, DOM JSON, and selector candidates are saved.
  - Given non-standard UI, when visual analysis runs, then at least one actionable locator is produced.
- Traceability hooks
  - RTM.id: FR-005

### FR-006 Requirements Synthesis – Features, Stories, AC
- Type: feature
- Priority: MUST
- Rationale
  - Create human-readable requirements from observed behavior.
- Description
  - Cluster pages into features and generate user stories with AC per feature using LLM prompts and templates.
- Inputs and outputs
  - Inputs: page map, element inventories.
  - Outputs: `docs/frd.md` section content and JSON export for RTM.
- Acceptance criteria
  - Given captured pages, when synthesis runs, then each feature area has at least one story with AC.
  - Given ambiguous flows, when critique pass runs, then low-quality stories are revised.
- Traceability hooks
  - RTM.id: FR-006

### FR-007 Test Scenario Derivation and Code Generation
- Type: feature
- Priority: MUST
- Rationale
  - Executable validation of requirements.
- Description
  - Derive scenarios from AC and render code in PyTest+Playwright and JUnit+Selenium; run syntax checks and optional dry runs.
- Inputs and outputs
  - Inputs: stories+AC, selectors.
  - Outputs: `/artifacts/tests/python/*.py`, `/artifacts/tests/java/*.java`, JUnit XML summaries.
- Acceptance criteria
  - Given AC, when generation runs, then at least one test per story is produced.
  - Given generated tests, when collected by PyTest or compiled with Maven, then no syntax or compile errors occur.
- Traceability hooks
  - RTM.id: FR-007

### FR-008 Artifact Packaging and Azure Blob Storage
- Type: feature
- Priority: MUST
- Rationale
  - Durable storage and sharing of outputs.
- Description
  - Upload artifacts to Azure Blob with per-run prefix and generate a JSON index with signed URLs where applicable.
- Inputs and outputs
  - Inputs: artifact files.
  - Outputs: `artifacts/index.json` with paths and metadata.
- Acceptance criteria
  - Given a completed run, when persistence runs, then all expected files are present and index lists them.
  - Given missing upload, when retry policy executes, then eventual consistency is reached or error is surfaced.
- Traceability hooks
  - RTM.id: FR-008

### FR-009 Public API and CLI
- Type: feature
- Priority: SHOULD
- Rationale
  - Programmatic control and CI integration.
- Description
  - REST API to create runs, stream status, list artifacts; CLI wrappers for local use.
- Acceptance criteria
  - Given API keys, when POST /runs is called from CI, then a run starts and status is retrievable.
  - Given a completed run, when CLI `gazeqa artifacts <id>` runs, then paths are printed and downloadable.
- Traceability hooks
  - RTM.id: FR-009

### FR-010 Web UI
- Type: feature
- Priority: SHOULD
- Rationale
  - Non-technical access and review.
- Description
  - Lovable-based frontend to submit runs, view live logs, coverage, FRD, and download tests.
- Acceptance criteria
  - Given a run in progress, when viewing the run detail, then logs, screenshots, and current step are visible in near real time.
  - Given a completed run, when opening FRD, then the rendered Markdown is readable and downloadable.
- Traceability hooks
  - RTM.id: FR-010

### FR-011 Observability and Telemetry
- Type: feature
- Priority: MUST
- Rationale
  - Diagnose and improve agent behavior.
- Description
  - Structured logs, metrics, traces; Langfuse for LLM spans; Temporal history linked to runs.
- Acceptance criteria
  - Given any LLM call, when viewed in Langfuse, then prompt, response, timing, and token counts are visible.
  - Given a failure, when searching logs by run id, then the failing step and screenshot are present.
- Traceability hooks
  - RTM.id: FR-011

### FR-012 Reliability and Recovery (Temporal)
- Type: feature
- Priority: MUST
- Rationale
  - Long flows must survive outages and flaky pages.
- Description
  - Activities with retries, backoff, idempotent checkpoints, and resume from last successful step.
- Acceptance criteria
  - Given a browser crash, when workflow resumes, then the browser is relaunched and the last page is reloaded.
  - Given transient network errors, when retries are applied, then the step succeeds without duplicating side effects.
- Traceability hooks
  - RTM.id: FR-012

### FR-013 Multi-tenant Permissions and Isolation
- Type: enhancement
- Priority: COULD (enable when SaaS)
- Description
  - Organization scoping for runs and artifacts; RBAC for submitter, viewer, admin.
- Acceptance criteria
  - Given two orgs, when viewing runs, then each org sees only its own data.
  - Given role viewer, when accessing settings, then access is denied.
- Traceability hooks
  - RTM.id: FR-013

### FR-014 Test Execution Orchestrator (Optional in v1)
- Type: enhancement
- Priority: COULD
- Description
  - Execute generated tests in sandboxed runners and collect results as JUnit XML with summary dashboard.
- Acceptance criteria
  - Given generated tests, when orchestrator runs, then pass/fail and traces are attached to the run.
  - Given failures, when viewing results, then failing steps include screenshots.
- Traceability hooks
  - RTM.id: FR-014

### FR-015 CI Integrations (GitHub Actions when available)
- Type: enhancement
- Priority: SHOULD
- Description
  - Provide sample workflow files gated behind repo detection; skip when repo is unavailable.
- Acceptance criteria
  - Given a GitHub repo, when action is enabled, then on push to main the platform triggers analysis and publishes artifacts.
  - Given no repo access, when configuring CI, then UI offers manual CLI instructions only.
- Traceability hooks
  - RTM.id: FR-015

### FR-016 Safety, Rate Limiting, and Guardrails
- Type: feature
- Priority: MUST
- Description
  - Throttle actions per domain; maintain allowlist/denylist; soft-delete or confirm destructive actions only in sandbox.
- Acceptance criteria
  - Given rate limits, when crawler runs, then requests per second stay under configured caps.
  - Given destructive UI elements, when encountered, then agent avoids them unless `sandbox_mode=true`.
- Traceability hooks
  - RTM.id: FR-016

### FR-017 Security Controls
- Type: feature
- Priority: MUST
- Description
  - Secret management, TLS, encryption at rest for storageState and artifacts, audit logs.
- Acceptance criteria
  - Given stored credentials, when inspecting logs and DB, then no plaintext secrets are present.
  - Given artifact downloads, when links are generated, then access requires authorization or time-bound SAS.
- Traceability hooks
  - RTM.id: FR-017

---

## 7. Non-Functional Requirements
- Performance and scalability
  - Targets: explore+capture p95 under 2 s per page on medium apps; complete 20-30 page app in under 30-60 min; support 5-10 concurrent runs per node initially.
- Reliability and resilience
  - At least 3 retries with jitter for flaky actions; DLQ for unrecoverable steps; resumable workflows.
- Security and compliance
  - TLS in transit; AES-256 at rest for sensitive blobs; bcrypt for user passwords when multi-tenant; basic SOC2-aligned controls.
- Privacy
  - Data minimization; per-run purge; tenant isolation.
- Observability
  - Dashboards: runs by status, coverage, tokens per run, login success rate; alerts on error rate spikes.
- Usability and accessibility
  - WCAG AA for UI basics; dark mode later.
- Maintainability and operability
  - Modular agents; config via env and typed config; runbooks for failures; SLOs for intake and artifact publish.

---

## 8. API Surface Summary
| Method | Path | Purpose | Auth | Request schema | Response schema | Errors |
|---|---|---|---|---|---|---|
| POST | /runs | Create analysis run | Bearer | CreateRun | RunCreated | 400, 401, 503 |
| GET | /runs/{id} | Get run status+metrics | Bearer | n/a | Run | 401, 404 |
| GET | /runs/{id}/artifacts | List artifacts | Bearer | n/a | ArtifactIndex | 401, 404 |
| WS | /runs/{id}/stream | Stream logs/events | Bearer | n/a | Event stream | 401, 404 |

---

## 9. Data Model Summary
- Entities
  - Run(id, params JSON, status, created_at, updated_at, metrics JSON)
  - Page(id, run_id, url, title, hash, screenshot_path, dom_path, selectors JSON)
  - Feature(id, run_id, name, page_ids[])
  - Story(id, feature_id, title, description, ac[])
  - TestCase(id, story_id, framework, path, status)
  - Artifact(id, run_id, type, path, size, checksum)
- Relationships
  - Run 1..N Page; Run 1..N Feature; Feature 1..N Story; Story 1..N TestCase.
- Migrations
  - Initial tables; forward-only with additive changes; backfill scripts where required.

---

## 10. Events and Integration Contracts
- Events
  - run.created v1, auth.success v1, page.visited v1, synthesis.done v1, tests.generated v1, run.completed v1
- External contracts
  - OpenAI Responses API; Browserbase sessions; Azure Blob REST; Temporal gRPC; Langfuse HTTP.

---

## 11. Security, Privacy, Compliance
- Threat model summary
  - Browser isolation, secret spillage prevention, unauthorized artifact access. Mitigations include container isolation, strict logging filters, and scoped SAS tokens.
- Secrets and key management
  - Env-only, never committed; optional vault integration later.
- Access control matrix
  - Roles: admin, operator, viewer. Admin can configure providers; operator runs; viewer reads artifacts.
- Compliance notes
  - Supports deployments aligned with SOC2 controls; HIPAA-ready storage via Azure configuration when needed.

---

## 12. Observability Plan
- Metrics
  - login_success_rate, pages_visited_total, coverage_percent, stories_count, tests_count, run_duration_seconds, tokens_total.
- Logs
  - Structured JSON with run_id, step, outcome, durations, error kinds.
- Traces
  - LLM spans with prompt ids; workflow spans per activity.
- Dashboards and alerts
  - Coverage under threshold; error spikes; long-running runs over SLA.

---

## 13. Environments and Deployment
- Environments
  - dev, staging, prod – Docker Compose; future Kubernetes.
- Config by environment
  - Provider keys, rate limits, Blob containers, telemetry toggles.
- Dependencies
  - Temporal, Postgres or Supabase (metadata), Redis optional, Azure Blob, Caddy reverse proxy.
- Deployment strategy
  - Blue-green or rolling; manual gates; Infra-as-Code with Terraform for Hetzner/Azure.

---

## 14. Rollout and Safeguards
- Feature flags and kill switches
  - Disable CUA, force deterministic-only; disable form submissions; pause external calls.
- Rollout plan
  - Internal apps first, then pilot customers; expand concurrency by node.
- Auto-rollback criteria
  - Error rate over 10 percent for new release; coverage drop over 5 points.

---

## 15. Testing and Acceptance Plan
- Strategy
  - Unit for utilities, integration for API, e2e for orchestrator happy path, contract tests for API, performance smoke.
- Test data and fixtures
  - Seeded demo app with stable routes; deterministic login script.
- Coverage targets and gating
  - 80 percent lines minimum; RTM maps 100 percent of stories to at least one test.
- Mapping to acceptance criteria
  - RTM ties FR-XXX to scenarios and checks; CI gate blocks on unmet AC.

---

## 16. Milestones and Deliverables
- M0: Orchestrator, login, explore+crawl, page capture, Azure Blob persistence.
- M1: Requirements synthesis and test generation in PyTest and JUnit; artifact index and downloads.
- M2: Optional execution orchestrator; CI samples; coverage dashboard.

---

## 17. Success Metrics and KPIs
- Engineering
  - Lead time from run to artifacts; change failure rate under 10 percent; mean time to recovery under 10 min.
- Product
  - Coverage percent, story-to-test ratio ≥ 0.98, user-attributed time saved, repeat run adoption.

---

## 18. Risks and Mitigations
- Aggressive bot defenses block automation – use Browserbase stealth, proxies, scripted fallbacks, and allow user-provided paths.
- Model drift or API quota issues – version prompts, support model fallback, monitor quotas with backoff.

---

## 19. Assumptions and Open Questions
- Assumptions
  - Authorized testing only; valid credentials provided when required; web UI accessible in Chromium.
- Open questions
  - Preferred on-prem model option for regulated customers in phase 2.
  - Required data retention period per customer and purge SLAs.

---

## 20. Glossary
- CUA: Computer Use Agent controlling a browser like a human.
- storageState: Playwright JSON for reusable session cookies and tokens.
- Coverage: ratio of discovered pages or validated AC to estimated total.

---

## 21. Change Log
- v1.0.0 2025-09-16: Initial FRD covering autonomous exploration, requirements synthesis, test generation, persistence, observability, and optional execution.
