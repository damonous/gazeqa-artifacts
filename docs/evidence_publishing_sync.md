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
4. **Dashboard export** (Codex agent)
   - Ensure metrics for the run are tagged with `run_id`; dashboards referenced in `docs/observability_dashboard_plan.md` will ingest data automatically.

4. **Metrics export** (agent executing run)
   - Run `python3 tools/run_summary_to_metrics.py artifacts/<date>/<run-id>/run_summary.json --checklist docs/gaze_qa_checklist_v_4.json --output metrics/<run-id>.prom`.
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
- Agent Beta: extend synthesis + generated test coverage beyond RUN-FR006-009-001 and wire packaging automation for follow-on runs.
- Codex agent: verify checklist diffs nightly and adjust alert thresholds as data matures.

Following this process keeps the RTM checklist synchronized with live evidence and supports rapid triage of regressions.
