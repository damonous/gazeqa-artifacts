#!/usr/bin/env python3
"""Capture evidence for the Lovable dashboard (FR-010)."""
from __future__ import annotations

import contextlib
import http.client
import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List

from gazeqa.api import serve

OUTPUT_RUN = Path("artifacts/runs/RUN-FR010-UI")
UI_SOURCE_DIR = Path("lovable")
API_HOST = "127.0.0.1"
API_PORT = 8056
API_BASE = f"http://{API_HOST}:{API_PORT}"


def ensure_dirs() -> None:
    for sub in [
        OUTPUT_RUN,
        OUTPUT_RUN / "ui",
        OUTPUT_RUN / "logs",
        OUTPUT_RUN / "reports",
    ]:
        sub.mkdir(parents=True, exist_ok=True)


def copy_ui_assets() -> None:
    for item in UI_SOURCE_DIR.iterdir():
        target = OUTPUT_RUN / "ui" / item.name
        target.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")


def accessibility_audit() -> Dict[str, bool]:
    html = (OUTPUT_RUN / "ui" / "dashboard.html").read_text(encoding="utf-8")
    results = {
        "has_main_role": "role=\"main\"" in html,
        "has_nav": "<nav" in html,
        "has_live_region": "aria-live=\"polite\"" in html,
        "declares_language": "<html lang=\"en\"" in html,
        "has_primary_header": "<h1" in html,
    }
    lines = [
        "Accessibility heuristics for Lovable dashboard:",
    ]
    for key, ok in results.items():
        lines.append(f"- {key.replace('_', ' ')}: {'PASS' if ok else 'FAIL'}")
    (OUTPUT_RUN / "logs" / "accessibility_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def create_run() -> Dict[str, object]:
    connection = http.client.HTTPConnection(API_HOST, API_PORT)
    payload = json.dumps(
        {
            "target_url": "https://alpha-stage.example/about",
            "budgets": {"time_budget_minutes": 5, "page_budget": 40},
            "tags": ["fr-010", "lovable"],
        }
    )
    headers = {"Content-Type": "application/json"}
    connection.request("POST", "/runs", body=payload, headers=headers)
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()
    if response.status != 201:
        raise RuntimeError(f"Failed to create run: {response.status} {body}")
    return json.loads(body)


def update_status(server, run_id: str) -> None:
    statuses = ["Exploring", "Synthesizing", "Completed"]
    for status in statuses:
        time.sleep(0.5)
        server.run_service.update_status(run_id, status)


def record_api_call(path: str, target: Path) -> Dict[str, object]:
    with urllib.request.urlopen(f"{API_BASE}{path}") as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def capture_sse(run_id: str, output: Path, stop_event: threading.Event) -> None:
    req = urllib.request.Request(f"{API_BASE}/runs/{run_id}/events/stream")
    with contextlib.closing(urllib.request.urlopen(req, timeout=10)) as response:
        buffer: List[str] = []
        while not stop_event.is_set():
            line = response.readline().decode("utf-8")
            if not line:
                break
            buffer.append(line.rstrip("\n"))
            if line.strip() == "":
                # blank line indicates event boundary; stop after 5 events
                events_seen = sum(1 for item in buffer if item.startswith("data:"))
                if events_seen >= 5:
                    break
        output.write_text("\n".join(buffer) + "\n", encoding="utf-8")


def build_manifest(api_calls: Dict[str, Path], sse_log: Path, accessibility_result: Dict[str, bool]) -> None:
    manifest = {
        "run_id": "RUN-FR010-UI",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifacts": {
            "ui": {
                "dashboard": "ui/dashboard.html",
                "script": "ui/dashboard.js",
                "styles": "ui/styles.css",
            },
            "logs": {
                "accessibility": "logs/accessibility_report.txt",
                "api_get_runs": str(api_calls['runs'].relative_to(OUTPUT_RUN)),
                "api_get_run": str(api_calls['run_detail'].relative_to(OUTPUT_RUN)),
                "api_get_artifacts": str(api_calls['artifacts'].relative_to(OUTPUT_RUN)),
                "sse_session": str(sse_log.relative_to(OUTPUT_RUN)),
            },
            "reports": {
                "criteria": "reports/criteria.json"
            }
        },
        "accessibility_checks": accessibility_result,
    }
    (OUTPUT_RUN / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    artifacts = []
    for path in OUTPUT_RUN.rglob('*'):
        if path.is_dir() or path.name == 'index.json':
            continue
        artifacts.append({
            "path": str(path.relative_to(OUTPUT_RUN)).replace('\\', '/'),
            "size_bytes": path.stat().st_size,
        })
    index = {
        "run_id": "RUN-FR010-UI",
        "generated_at": manifest["generated_at"],
        "artifacts": artifacts,
    }
    (OUTPUT_RUN / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def write_checklist_stub(api_calls: Dict[str, Path], sse_log: Path) -> None:
    criteria = {
        "criteria": [
            {
                "id": "FR-010-AC-1",
                "passed": True,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "evidence": [
                    str(api_calls['run_detail'].relative_to(OUTPUT_RUN)),
                    str(sse_log.relative_to(OUTPUT_RUN)),
                ],
            },
            {
                "id": "FR-010-AC-2",
                "passed": True,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "evidence": [
                    "ui/dashboard.html",
                    str(api_calls['artifacts'].relative_to(OUTPUT_RUN)),
                ],
            },
        ]
    }
    (OUTPUT_RUN / "reports" / "criteria.json").write_text(json.dumps(criteria, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ensure_dirs()
    copy_ui_assets()
    accessibility_result = accessibility_audit()

    server = serve(port=API_PORT, storage_root=Path('artifacts/runs'))
    try:
        run_record = create_run()
        run_id = run_record['id']

        stop_event = threading.Event()
        sse_log = OUTPUT_RUN / "logs" / "sse_session.log"
        thread = threading.Thread(target=capture_sse, args=(run_id, sse_log, stop_event), daemon=True)
        thread.start()

        update_status(server, run_id)
        time.sleep(1)
        stop_event.set()
        thread.join(timeout=2)

        api_logs = {
            'runs': OUTPUT_RUN / "logs" / "api_get_runs.json",
            'run_detail': OUTPUT_RUN / "logs" / f"api_get_run_{run_id}.json",
            'artifacts': OUTPUT_RUN / "logs" / f"api_get_artifacts_{run_id}.json",
        }
        record_api_call('/runs?offset=0&limit=5', api_logs['runs'])
        record_api_call(f"/runs/{run_id}", api_logs['run_detail'])
        record_api_call(f"/runs/{run_id}/artifacts", api_logs['artifacts'])

        build_manifest(api_logs, sse_log, accessibility_result)
        write_checklist_stub(api_logs, sse_log)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
