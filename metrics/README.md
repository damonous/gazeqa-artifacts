# Metrics Export Artifacts

Prometheus text-format files produced by `tools/run_summary_to_metrics.py` land here during CI runs. The directory is intentionally empty in source control; CI uploads generated files as artifacts.

To test locally:
1. Run your pipeline to generate `artifacts/<date>/<run-id>/run_summary.json`.
2. Execute:
   ```bash
   python3 tools/run_summary_to_metrics.py artifacts/<date>/<run-id>/run_summary.json \
     --checklist docs/gaze_qa_checklist_v_4.json \
     --observability artifacts/<date>/<run-id>/observability/metrics.json \
     --output metrics/gazeqa_metrics.prom
   ```
3. Point Prometheus to scrape the resulting `.prom` file (e.g., via node_exporter textfile collector) or curl it with a local HTTP file server.

Generated files should not be committed; add them to `.gitignore` if needed.
