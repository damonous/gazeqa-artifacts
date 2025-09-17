# Manual CLI Instructions (FR-015-AC-2)

For teams without GitHub repository access, the following steps reproduce the CI pipeline from a local environment:

1. Export `PYTHONPATH=$PWD` inside the repo.
2. Execute `python tools/test_execution_orchestrator.py artifacts/runs/RUN-FR006-009-004/tests/manifest.json --output artifacts/runs/RUN-FR014-LOCAL` to run generated suites and emit JUnit/trace artifacts.
3. Execute `python tools/capture_ui_evidence.py` to collect API snapshots, SSE transcript, and accessibility report.
4. Upload the resulting `artifacts/runs/RUN-FR014-LOCAL` and `artifacts/runs/RUN-FR010-UI` directories to your storage provider or attach them to the ticket for review.

These instructions mirror the steps automated by `.github/workflows/gazeqa-artifacts.yml` and satisfy FR-015-AC-2 without requiring repository-level automation.
