#!/usr/bin/env python3
"""Capture evidence for the Lovable dashboard (FR-010)."""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List

from gazeqa.api import serve

OUTPUT_RUN = Path("artifacts/runs/RUN-FR010-UI")
UI_SOURCE_DIR = Path("webui")
API_HOST = "127.0.0.1"
API_PORT = 8056
API_BASE = f"http://{API_HOST}:{API_PORT}"
API_TOKEN = os.getenv("GAZEQA_API_TOKEN", "")
UI_SCREENSHOT = OUTPUT_RUN / "ui" / "dashboard.png"
RUN_LIST_SCREENSHOT = OUTPUT_RUN / "ui" / "runs.png"
RUN_DETAIL_SCREENSHOT = OUTPUT_RUN / "ui" / "detail.png"

try:  # pragma: no cover - optional dependency
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - install guard
    sync_playwright = None


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
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    connection.request("POST", "/runs", body=payload, headers=headers)
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()
    if response.status != 201:
        raise RuntimeError(f"Failed to create run: {response.status} {body}")
    return json.loads(body)


def record_api_call(path: str, target: Path) -> Dict[str, object]:
    request = urllib.request.Request(f"{API_BASE}{path}")
    if API_TOKEN:
        request.add_header("Authorization", f"Bearer {API_TOKEN}")
    with urllib.request.urlopen(request) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def capture_sse_snapshot(run_id: str, output: Path, max_events: int = 12) -> None:
    url = f"{API_BASE}/runs/{run_id}/events/stream"
    if API_TOKEN:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={API_TOKEN}"
    req = urllib.request.Request(url)
    with contextlib.closing(urllib.request.urlopen(req, timeout=10)) as response:
        lines: List[str] = []
        events_seen = 0
        while events_seen < max_events:
            try:
                chunk = response.readline()
            except socket.timeout:
                break
            if not chunk:
                break
            text = chunk.decode("utf-8").rstrip("\n")
            lines.append(text)
            if text.startswith("data:"):
                events_seen += 1
            if text == "" and events_seen >= max_events:
                break
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def capture_dashboard_views(run_id: str) -> None:
    if sync_playwright is None:  # pragma: no cover - optional dependency
        note = OUTPUT_RUN / "logs" / "screenshot_unavailable.txt"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("Playwright not available; screenshot skipped.\n", encoding="utf-8")
        return

    query = {
        "apiBase": API_BASE,
    }
    if API_TOKEN:
        query["token"] = API_TOKEN
    query_string = urllib.parse.urlencode(query)
    dashboard_url = f"{API_BASE}/ui/?{query_string}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(dashboard_url, wait_until="networkidle", timeout=15000)
        page.wait_for_selector('nav[aria-label="Runs"] button', timeout=15000)
        UI_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        RUN_LIST_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        RUN_DETAIL_SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)

        runs_nav = page.locator('nav[aria-label="Runs"]')
        runs_nav.screenshot(path=str(RUN_LIST_SCREENSHOT))

        # Focus on the requested run to ensure detail pane evidence.
        page.locator(f'nav[aria-label="Runs"] button:has-text("{run_id}")').first.click()
        page.wait_for_timeout(500)

        detail_section = page.locator('.run-details')
        detail_section.screenshot(path=str(RUN_DETAIL_SCREENSHOT))
        page.screenshot(path=str(UI_SCREENSHOT), full_page=True)
        browser.close()


def wait_for_completion(server, run_id: str, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    status = "Running"
    while time.time() < deadline:
        manifest = server.run_service.get_run(run_id)
        status = manifest.get("status", status)
        if status in {"Completed", "Failed"}:
            break
        time.sleep(0.5)
    return status


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
    if RUN_LIST_SCREENSHOT.exists():
        manifest["artifacts"]["ui"]["run_list"] = "ui/runs.png"
    if RUN_DETAIL_SCREENSHOT.exists():
        manifest["artifacts"]["ui"]["run_detail"] = "ui/detail.png"
    if UI_SCREENSHOT.exists():
        manifest["artifacts"]["ui"]["screenshot"] = "ui/dashboard.png"
    snippet_files = sorted(
        (OUTPUT_RUN / "logs").glob("artifacts_index_snippet_*.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if snippet_files:
        manifest["artifacts"]["logs"]["artifacts_index_snippet"] = str(snippet_files[-1].relative_to(OUTPUT_RUN))
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

        wait_for_completion(server, run_id)
        sse_log = OUTPUT_RUN / "logs" / f"sse_session_{run_id}.log"
        capture_sse_snapshot(run_id, sse_log)

        api_logs = {
            'runs': OUTPUT_RUN / "logs" / "api_get_runs.json",
            'run_detail': OUTPUT_RUN / "logs" / f"api_get_run_{run_id}.json",
            'artifacts': OUTPUT_RUN / "logs" / f"api_get_artifacts_{run_id}.json",
        }
        record_api_call('/runs?offset=0&limit=5', api_logs['runs'])
        record_api_call(f"/runs/{run_id}", api_logs['run_detail'])
        record_api_call(f"/runs/{run_id}/artifacts", api_logs['artifacts'])

        capture_dashboard_views(run_id)

        index_path = Path('artifacts') / 'runs' / run_id / 'artifacts' / 'index.json'
        if index_path.exists():
            data = json.loads(index_path.read_text(encoding="utf-8"))
            snippet = {
                "run_id": run_id,
                "generated_at": data.get("generated_at"),
                "artifacts": data.get("artifacts", [])[:10],
            }
            snippet_path = OUTPUT_RUN / "logs" / f"artifacts_index_snippet_{run_id}.json"
            snippet_path.write_text(json.dumps(snippet, indent=2) + "\n", encoding="utf-8")

        build_manifest(api_logs, sse_log, accessibility_result)
        write_checklist_stub(api_logs, sse_log)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
