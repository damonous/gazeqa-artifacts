# Observability Dashboard Plan

- Version: 2025-09-16 draft
- Owner: Codex agent
- Scope: FR-011 (Observability & Telemetry), FR-012 (Reliability), FR-016 (Safety), FR-017 (Security) support

## Objectives
- Provide at-a-glance status for RTM Done Definition KPIs (coverage, story-to-test coverage, artifact persistence).
- Correlate Temporal workflows, Langfuse LLM spans, and automation evidence for each run ID.
- Alert engineering leads (Agents Alpha, Beta, Codex) when regressions or anomalies occur.

## Data Sources
- **Temporal**: workflow executions, retries, activity failures, checkpoint metadata.
- **Langfuse**: LLM prompt/response spans, token usage, latency per run.
- **Application logs**: structured logs with `run_id`, `component`, `severity`.
- **Metrics pipeline** (OpenTelemetry / Prometheus): gauges + counters for coverage, story/test coverage, artifact uploads, rate limiting, guardrail hits.
- **Artifacts index**: `artifacts/index.json` emitted in FR-008.
- **Checklist updater outputs**: `docs/gaze_qa_checklist_v_4.json` summary block, `criteria_complete`, `tests_complete` flags.

## Dashboards

### Metrics Export Utility
- Use `tools/run_summary_to_metrics.py` after each automation run to produce Prometheus text-format metrics (consume via node_exporter textfile collector or custom scrape target).
- Command example: `python3 tools/run_summary_to_metrics.py artifacts/<date>/<run-id>/run_summary.json --checklist docs/gaze_qa_checklist_v_4.json --observability artifacts/<date>/<run-id>/observability/metrics.json --output metrics/latest.prom`.
- Metrics exposed: `gazeqa_tests_total`, `gazeqa_tests_passed`, `gazeqa_tests_failed`, `gazeqa_criteria_total`, `gazeqa_criteria_passed`, and global checklist gauges.

### 1. Run Overview
- **KPIs**: coverage_percent, story_to_test_coverage, artifact_upload_success_rate, requirements_verified.
- **Widgets**: run list (last 20), sparkline for coverage trends, donut of requirement status (Verified / Incomplete / Blocked).
- **Correlated links**: download FRD, tests, selectors, Temporal history, Langfuse session.

### 2. Exploration & Capture (Alpha focus)
- Metrics: pages_visited_total, coverage_percent, loop_breaker_triggers, crawl_skipped_urls.
- Logs: login success/failure timeline annotated with guardrail hits.
- Alerts: coverage_percent < 0.97 or rate limiting violations > 0 per run.

### 3. Generation & Delivery (Beta focus)
- Metrics: story_count, story_to_test_coverage, test_generation_errors, artifact_upload_latency, API/CLI latency.
- Visuals: stacked bar of test frameworks (PyTest, JUnit) pass/fail, artifact size histogram.
- Alerts: story_to_test_coverage < 0.98, artifact upload retries > 3, CLI/API latency > SLA.

### 4. Observability & Safety (Codex focus)
- Metrics: Temporal retry counts, DLQ backlog, guardrail_block_events, secret_redaction_failures.
- Langfuse view: heatmap of LLM cost per run, failure drilldown.
- Alerts: DLQ backlog > 0, guardrail_block_events triggered in production env, secrets_not_redacted > 0.

## Implementation Steps
1. **Instrumentation**
   - Ensure all services emit structured logs with `run_id`, `organization_slug`, `component`, `severity`, `env`.
   - Export coverage metrics (FR-003/004) via Prometheus gauge `gazeqa_coverage_percent{run_id}`.
   - Emit `gazeqa_story_to_test_coverage{run_id}` from FR-007 pipeline.
   - Record artifact upload success/failure counters `gazeqa_artifact_upload_total{status}` in FR-008.
   - Publish guardrail metrics `gazeqa_guardrail_block_total{action}` from FR-016 logic.

2. **Data Pipeline**
- Configure OpenTelemetry collectors to forward metrics/logs to central TSDB (Prometheus/Grafana) and log store (ELK or Loki).
- Connect Langfuse project to Grafana via plugin or embed external dashboard link.
- Integrate Temporal visibility API for workflow stats; push key metrics to Prometheus (retries, duration).
- Route Prometheus alerts through the bundled Alertmanager -> `/observability/alerts` webhook so the API audit log captures incidents (and onward integrations can fan out from there).

3. **Dashboard Creation**
   - Build Grafana dashboards per sections above; store JSON definitions under `observability/dashboards/` (to be created) for version control.
   - Parameterize dashboards by `run_id` and `env` to filter data.
   - Document panels and expected queries in `observability/README.md` (future work).

4. **Alerts & Notifications**
   - Configure alert rules for KPI thresholds (coverage < 0.97, story/test < 0.98, artifact failure spikes).
   - Route alerts to shared channel or PagerDuty rotation based on env.
   - Add weekly summary report exporting metrics snapshot to `docs/metrics/reports/<date>.md` (future automation task).

5. **Hand-off & Maintenance**
   - Dashboard JSON stored under `observability/dashboards/gazeqa_overview.json`; alerts defined in `observability/alerts/gazeqa_alerts.yaml`.
   - Agents Alpha & Beta validate dashboards against their pipelines once instrumentation lands.
   - Codex agent reviews alert noise weekly; adjust thresholds as data stabilizes.
   - Keep dashboards updated when RTM adds new requirements or KPIs.

## Deliverables Tracker
- [ ] Structured logging schema documented (Codex agent).
- [ ] Prometheus metric exporters implemented (Agents Alpha/Beta for respective components).
- [ ] Grafana dashboards exported to repo (`observability/dashboards/`).
- [ ] Alert rules configured and reviewed.
- [ ] Weekly metrics summary automation defined.

This plan should be revisited once instrumentation PRs land to ensure the dashboards reflect real signal.
