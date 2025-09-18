# CI Pipeline & API Evidence (FR-009, FR-015)

## API Evidence (FR-009)
- `GET /runs`: captured in `artifacts/runs/RUN-FR010-UI/logs/api_get_runs.json` using token-authenticated dashboard requests.
- `GET /runs/{id}`: evidence at `artifacts/runs/RUN-FR010-UI/logs/api_get_run_RUN-D21B8821286A.json` (active run manifest).
- `GET /runs/{id}/artifacts`: see `artifacts/runs/RUN-FR010-UI/logs/api_get_artifacts_RUN-D21B8821286A.json`.
- `GET /runs/{id}/events` + SSE stream: transcript stored at `artifacts/runs/RUN-FR010-UI/logs/sse_session_RUN-D21B8821286A.log`; dashboard shows live feed in `webui/dashboard.html`.
- Artifacts index excerpt for evidence bundling: `artifacts/runs/RUN-FR010-UI/logs/artifacts_index_snippet_RUN-D21B8821286A.json`.

## CI Orchestrator Evidence (FR-014, FR-015)
- CI workflow definition: `.github/workflows/gazeqa-artifacts.yml` provisions Python + Playwright, generates test artifacts, runs `tools/test_execution_orchestrator.py`, and uploads evidence bundles.
- Workflow execution log: `artifacts/runs/RUN-FR014-EXEC/logs/github_workflow.log`.
- Generated suite outputs: `artifacts/runs/RUN-FR014-EXEC/execution/junit_python.xml`, `artifacts/runs/RUN-FR014-EXEC/execution/trace.json`, `artifacts/runs/RUN-FR014-EXEC/logs/pytest.log`.
- Metrics snapshot emitted post-run: `artifacts/runs/RUN-FR014-EXEC/reports/metrics_snapshot.prom`.
- Checklist references updated via `artifacts/runs/RUN-FR014-EXEC/run_summary.json` followed by `docs/checklist_autoupdate.py`.

## Triggering CI Runs
1. Push to `main` or dispatch manually via GitHub Actions UI.
2. Workflow stages:
   - Install dependencies & Playwright (`python -m playwright install --with-deps chromium`).
   - Generate selectors/tests: `python tools/run_pipelines.py --run-id $CI_RUN_ID --output-root artifacts/runs`.
   - Execute orchestration: `python tools/test_execution_orchestrator.py artifacts/runs/$CI_RUN_ID/tests/manifest.json --output artifacts/runs/$CI_EXEC_RUN_ID`.
   - Capture Lovable UI evidence with `GAZEQA_API_TOKEN` provided.
   - Upload artifacts (`gazeqa-generated-tests`, `gazeqa-junit`, `gazeqa-ui-evidence`).
3. After completion, run summaries feed metrics (`metrics/RUN-FR014-EXEC.prom`) and `docs/gaze_qa_checklist_v_4.json` via the auto-update script.

Keep the above logs and metrics under version control for auditability and nightly checklist verification.
