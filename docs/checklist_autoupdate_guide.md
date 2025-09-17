# Checklist Auto-Update Integration

- Version: 2025-09-16 draft
- Generated: 2025-09-16
- Owner: Codex agent (automation lead)

This guide describes how to feed automated run results into `docs/gaze_qa_checklist_v_4.json` so requirement verification status is kept current without manual editing.

## Utility Overview

`docs/checklist_autoupdate.py` reads a run summary JSON file produced by the automation pipeline and updates the checklist entries:

- Marks acceptance criteria as passed/failed based on recorded evidence and tracks whether every criterion has been evaluated (`criteria_complete`).
- Updates per-requirement test coverage using test case status and records whether all expected test cases reported results (`tests_complete`).
- Recomputes the global checklist summary metrics.
- Stores run metadata (environment, build SHA, run id) for traceability.
- Leaves a requirement flagged as unverified when criteria evidence is missing, even if test coverage is green—highlighting partial automation.

## Acceptance Criteria Evidence

Until AC checks are fully automated, you can:

1. Generate criteria verdicts from scripted probes (recommended). Emit JSON documents matching the schema below and pass them via `--criteria-json`.
2. Capture manual review outcomes by hand-curating a small JSON file after exploratory testing. This still feeds the checklist so the RTM reflects real-world evidence.

Each criteria JSON file may look like:

```json
{
  "criteria": [
    {
      "id": "FR-003-AC-1",
      "passed": true,
      "checked_at": "2025-09-16T09:20:00Z",
      "evidence": ["artifacts/run-22/coverage_report.json"]
    }
  ]
}
```

Multiple files can be supplied; the updater merges them.

## Generating Run Summary JSON with the Builder Script

Use `tools/build_run_summary.py` to translate existing automation outputs into the expected schema. Key options:

- `--run-id` *(required)*: unique identifier per pipeline execution.
- `--env`: environment label (defaults to `ci`).
- `--build-sha`: commit SHA or build identifier.
- `--artifact-root`: base directory prefixed to relative evidence paths.
- `--junit`: path to JUnit XML (`pytest --junitxml`, Playwright, etc.). Repeatable if multiple reports exist. JUnit testcase names should match RTM test IDs; if they differ, use `--test` overrides or emit a dedicated JUnit report for RTM-facing suites.
- `--test`: fallback for ad-hoc results in the form `TEST_ID=STATUS` (repeatable).
- `--test-evidence`: JSON files mapping test IDs to extra evidence paths (repeatable) to augment JUnit data.
- `--criteria-json`: JSON files containing acceptance criteria results. Each file may be either a list of criteria objects or an object with a `criteria` array.
- `--output` *(required)*: destination for the generated run summary JSON.

Example:

```bash
python3 tools/build_run_summary.py \
  --run-id "${RUN_ID}" \
  --env "qa" \
  --build-sha "${GIT_SHA}" \
  --artifact-root artifacts/latest \
  --junit artifacts/latest/junit.xml \
  --criteria-json artifacts/latest/criteria.json \
  --output artifacts/latest/run_summary.json
```

If acceptance criteria checks are not automated yet, omit `--criteria-json`; the generated summary will contain an empty `criteria` array and the checklist will show `criteria_complete=false`.

## Run Summary Schema

The resulting JSON should conform to the structure below (fields marked *optional* may be omitted):

```json
{
  "run_id": "RUN-2025-09-16-001",
  "env": "qa",
  "build_sha": "2c591d9",
  "started_at": "2025-09-16T07:00:00Z",
  "finished_at": "2025-09-16T08:05:00Z",
  "tests": [
    {
      "id": "TC-FR-001-001",
      "status": "passed",
      "evidence": ["artifacts/2025-09-16/run-1/api/create-run-201.json"]
    },
    {
      "id": "TC-FR-002-001",
      "status": "failed",
      "evidence": ["artifacts/2025-09-16/run-1/screenshots/login-fallback.png"]
    }
  ],
  "criteria": [
    {
      "id": "FR-001-AC-1",
      "passed": true,
      "checked_at": "2025-09-16T07:05:00Z",
      "evidence": ["artifacts/2025-09-16/run-1/api/create-run-201.json"]
    },
    {
      "id": "FR-002-AC-1",
      "passed": false,
      "checked_at": "2025-09-16T07:20:00Z",
      "evidence": ["artifacts/2025-09-16/run-1/logs/login-timeout.log"]
    }
  ]
}
```

Notes:
- `tests[].status` accepts `passed`, `failed`, or any other string (only `passed` counts toward coverage).
- Evidence paths may be relative; pass `--artifact-root` to prefix them with an absolute location during summary generation or use `--evidence-root` during the checklist update.

## Updating the Checklist Locally

1. Produce a run summary JSON (e.g., via the builder script).
2. Execute the updater:

```bash
python3 docs/checklist_autoupdate.py artifacts/latest/run_summary.json --evidence-root artifacts/latest
```

3. Review `git diff docs/gaze_qa_checklist_v_4.json` to confirm the expected verification updates and ensure `criteria_complete/tests_complete` reflect reality.

## CI/GitHub Actions Integration

Add post-run steps that use the builder followed by the checklist updater.

```yaml
- name: Build checklist run summary
  run: |
    python3 tools/build_run_summary.py \
      --run-id "${{ github.run_id }}" \
      --env "ci" \
      --build-sha "${{ github.sha }}" \
      --artifact-root artifacts \
      --junit artifacts/junit.xml \
      --output artifacts/run_summary.json

- name: Update RTM checklist
  run: |
    python3 docs/checklist_autoupdate.py artifacts/run_summary.json --evidence-root artifacts

- name: Upload updated checklist artifact
  uses: actions/upload-artifact@v4
  with:
    name: gazeqa-checklist
    path: |
      docs/gaze_qa_checklist_v_4.json
      artifacts/run_summary.json
```

(Extend the workflow to include `--criteria-json` and additional evidence maps once those signals are produced.)

## Observability Dashboard Tie-in

- Capture generated `run_summary.json` and updated checklist as inputs to the planned RTM dashboard.
- Emit metrics such as `requirements_verified`, `criteria_complete`, and `tests_complete` counts into your telemetry stack after each update.
- Alert when any previously verified requirement regresses or when `criteria_complete` remains false for more than one run.

## Operational Checklist

- [ ] Run summary builder integrated into the automation pipeline.
- [ ] Checklist updater executed in CI/CD after each automation run.
- [ ] Acceptance criteria verdicts (automated or manual) exported via `--criteria-json`.
- [ ] Updated checklist published for stakeholders (artifact, dashboard, or docs site).
- [ ] Alerts triggered when previously verified requirements regress or when criteria remain incomplete.

Keeping the checklist authoritative ensures the RTM stays in sync with real execution evidence and highlights regressions immediately.
