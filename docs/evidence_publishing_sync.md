# Evidence Publishing Sync

- Date: 2025-09-16
- Participants: Codex agent, Agent Alpha, Agent Beta
- Purpose: establish repeatable flow for publishing run evidence, run summaries, and checklist updates.

## Evidence Pipeline
1. **Run execution** (Alpha/Beta)
   - Produce artifacts under `artifacts/<date>/<run-id>/` containing logs, screenshots, selectors, FRD, generated tests.
   - Export JUnit XML (test IDs must match RTM catalog) and optional coverage reports.
2. **Run summary generation** (responsible agent)
   - Invoke `python3 tools/build_run_summary.py` with:
     - `--run-id` set to timestamped identifier (`RUN-YYYYMMDD-HHMM-<component>`).
     - `--env` matching execution environment (`dev`, `qa`, `ci`, `prod`).
     - `--artifact-root` pointing to the artifacts directory.
     - `--criteria-json` for any acceptance-criteria verdicts (scripted or manual).
     - `--output artifacts/<date>/<run-id>/run_summary.json`.
3. **Checklist update** (responsible agent)
   - Execute `python3 docs/checklist_autoupdate.py artifacts/<date>/<run-id>/run_summary.json --evidence-root artifacts/<date>/<run-id>`.
   - Commit or upload updated `docs/gaze_qa_checklist_v_4.json` via CI artifact.
4. **UI evidence capture (FR-010)**
   - Run `python3 tools/capture_ui_evidence.py` (requires `GAZEQA_API_TOKEN`) to spin up the `webui/` Lovable dashboard against the live API.
   - Outputs stored under `artifacts/runs/RUN-FR010-UI/`:
     - `ui/runs.png` (run list) and `ui/detail.png` (detail pane) screenshots.
     - `ui/dashboard.png` full-page capture and `logs/sse_session_<run>.log` SSE transcript with `?token=` auth.
     - `logs/artifacts_index_snippet_<run>.json` capturing the artifacts index excerpt for FR-009 evidence.
5. **Metrics export / dashboards** (Codex agent)
   - Ensure metrics for the run are tagged with `run_id`; dashboards referenced in `docs/observability_dashboard_plan.md` will ingest data automatically.
   - Run `python3 tools/run_summary_to_metrics.py artifacts/<date>/<run-id>/run_summary.json --checklist docs/gaze_qa_checklist_v_4.json --observability artifacts/<date>/<run-id>/observability/metrics.json --output metrics/<run-id>.prom`.
   - Upload `.prom` file via CI artifact or expose through Prometheus textfile collector so dashboards receive updated gauges.

## Communication Cadence
- **Daily**: Agents Alpha/Beta post run IDs, coverage metrics, and checklist status (`criteria_complete/tests_complete`) in the shared channel.
- **After each regression**: Codex agent reviews guardrail/observability alerts and coordinates fixes with responsible agent.
- **Weekly**: Consolidated metrics report published (future automation) and reviewed in standup.

## Ownership Matrix
| Artifact | Primary Owner | Backup |
| --- | --- | --- |
| Run artifacts (`artifacts/<date>/<run-id>/`) | Agent executing run | Same team |
| Run summary JSON | Agent executing run | Codex agent |
| Checklist update | Agent executing run | Codex agent |
| Dashboard metrics | Codex agent | Agent Alpha (exploration metrics), Agent Beta (generation metrics) |

## Next Actions
- Agent Alpha: produce first authenticated exploration run summary to validate criteria recording.
- Agent Beta: extend synthesis/testing using adjacency-driven runs (e.g., RUN-FR006-009-004) and attach live API responses for FR-009.
- Codex agent: verify checklist diffs nightly and adjust alert thresholds as data matures.

Following this process keeps the RTM checklist synchronized with live evidence and supports rapid triage of regressions.

- API responses (`GET /runs`, `GET /runs/<id>`, `GET /runs/<id>/artifacts`) should be captured for checklist updates covering FR-009 tests.
- Web UI: `tools/capture_ui_evidence.py` now captures run list/detail screenshots, SSE transcripts, and an artifacts index snippet for FR-010 and FR-009 coverage.
- Reliability runs store checkpoints under `temporal/checkpoints.jsonl` and status history via API (`POST /runs/{id}/status`) for FR-012 evidence.

## FR-015 CI Workflow Notes
- GitHub Actions workflow `.github/workflows/gazeqa-artifacts.yml` executes `tools/run_pipelines.py`, runs the orchestrator (`tools/test_execution_orchestrator.py`), and collects UI evidence.
- Required secrets: `GAZEQA_API_TOKEN` (Bearer token for API/UI), optional storage credentials for artifact buckets when publishing to external stores.
- Artifacts published by the workflow:
  - `gazeqa-generated-tests`: generated selectors/tests and orchestrator execution outputs.
  - `gazeqa-junit`: PyTest JUnit XML for downstream reporting.
  - `gazeqa-ui-evidence`: Lovable dashboard captures and SSE transcripts.
- Workflow execution trace stored at `artifacts/runs/RUN-FR014-EXEC/logs/github_workflow.log` and checklist evidence references `reports/ci_workflow.yml` + `reports/metrics_snapshot.prom` for FR-015 acceptance criteria.
