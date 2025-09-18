# Run Intake Quickstart (FR-001)

Use the packaged CLI or HTTP API to exercise the Task Intake flow.

## CLI

```bash
python -m gazeqa.cli docs/examples/create_run_payload.json
# or, if installed
#gazeqa-cli docs/examples/create_run_payload.json
```

Output includes the generated `run id`, budgets, and storage profile. Artifacts are stored under `artifacts/runs/<RUN-ID>/`.

## HTTP API

```bash
python -m gazeqa.api  # serves on http://127.0.0.1:8000
curl -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -d @docs/examples/create_run_payload.json
```

- Success ⇒ `201 Created` with run manifest JSON.
- Invalid payload ⇒ `400` with field-level errors, satisfying TC-FR-001-002.

## Tests

Run `python3 -m unittest discover -s tests` to execute unit/API tests covering FR-001 acceptance criteria.

Checklist evidence: capture the `201` response body and the `400` error payload for updated `docs/gaze_qa_checklist_v_4.json` entries.

## Exploration Sample

```python
from gazeqa.exploration import ExplorationEngine, ExplorationConfig, PageDescriptor

engine = ExplorationEngine(ExplorationConfig())
site_map = [
    PageDescriptor(url='https://example.test/home', title='Home', section='main'),
    PageDescriptor(url='https://example.test/dashboard', title='Dashboard', section='main'),
    PageDescriptor(url='https://example.test/settings', title='Settings', section='settings')
]
result = engine.explore('RUN-EXP-DEMO', site_map)
print(result.coverage_percent)
```

Artifacts land in `artifacts/runs/RUN-EXP-DEMO/exploration/` and can be referenced when building run summaries (`--test "TC-FR-003-001=passed"`).


## Authentication

Set `GAZEQA_API_TOKEN` to require Bearer auth for all API calls.

```bash
export GAZEQA_API_TOKEN="local-token"
curl -H "Authorization: Bearer $GAZEQA_API_TOKEN" http://127.0.0.1:8000/runs
```

## API Endpoints Snapshot

- `GET /runs` – list run identifiers stored on disk.
- `GET /runs/<id>` – return the run manifest created via the CLI/API intake flow.
- `GET /runs/<id>/artifacts` – generate and return `artifacts/index.json` (FR-008 manifest).
- `POST /runs` – create a run (existing behaviour).

Capture `201`, `400`, and artifact manifest responses as evidence for FR-001/FR-008/FR-009 when updating the checklist.

## BFS Crawl Sample

```python
from gazeqa.crawl import BFSCrawler, CrawlConfig

crawler = BFSCrawler(CrawlConfig())
link_graph = {
    'https://example.test/home': ['https://example.test/about', 'https://example.test/settings'],
    'https://example.test/about': ['https://example.test/team']
}
result = crawler.crawl('RUN-CRAWL-DEMO', 'https://example.test/home', link_graph)
print(result.discovered_pages)
```

Artifacts saved to `artifacts/runs/RUN-CRAWL-DEMO/crawl/crawl_result.json` feed TC-FR-004-001.

### Pagination & Event Stream
- `GET /runs?offset=<n>&limit=<m>` paginates run listings (default 20). Use this before requesting artifact manifests for large histories.
- `GET /runs/<id>/events` returns a prototype Server-Sent Events stream (status updates). Capture responses for FR-009 checklist evidence.

API specification: `docs/api/openapi.yaml` provides schemas for CLI/UI integrations.

### Workflow Hooks
- `POST /runs/{id}/status` — append a status event (body: `{ "status": "Exploring", "metadata": {...} }`).
- `POST /runs/{id}/checkpoints` — record Temporal checkpoints (`{ "checkpoint": "exploration.complete", "details": {...} }`).
Use these from orchestration jobs so the SSE stream and dashboard stay current.

- `GET /runs/public/download?run_id=<id>&path=<artifact>&expires=<unix>&signature=<hmac>` — signed artifact download for Lovable/CLI (requires `GAZEQA_SIGNING_KEY`).
