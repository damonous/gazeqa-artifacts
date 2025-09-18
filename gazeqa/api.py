"""HTTP API for GazeQA: runs, artifacts, SSE, and Lovable UI assets."""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.parse
import hmac
import hashlib
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone

from .auth import build_auth_orchestrator
from .bfs import BFSCrawler, CrawlConfig
from .discovery import discover_site_map
from .exploration import ExplorationConfig, ExplorationEngine
from .models import ValidationError
from .observability import RunObservability
from .run_service import RunService
from .workflow import RunWorkflow


logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """Simple worker pool that executes workflows sequentially."""

    def __init__(self, workflow: RunWorkflow, *, max_workers: int = 2) -> None:
        self.workflow = workflow
        self.queue: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.workers: list[threading.Thread] = []
        for index in range(max(1, max_workers)):
            worker = threading.Thread(
                target=self._worker,
                name=f"workflow-worker-{index+1}",
                daemon=True,
            )
            worker.start()
            self.workers.append(worker)

    def submit(self, run_id: str) -> None:
        if self.stop_event.is_set():  # pragma: no cover - defensive
            raise RuntimeError("Workflow executor stopped")
        self.queue.put(run_id)

    def shutdown(self, timeout: float = 2.0) -> None:
        self.stop_event.set()
        deadline = None if timeout is None else (time.time() + timeout)
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:  # pragma: no cover - guard
                break
        for worker in self.workers:
            if deadline is None:
                worker.join()
            else:
                remaining = max(0.0, deadline - time.time())
                if remaining == 0:
                    break
                worker.join(timeout=remaining)

    def _worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                run_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.workflow.execute(run_id)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Workflow execution failed for run %s", run_id)
            finally:
                self.queue.task_done()


class RunRequestHandler(BaseHTTPRequestHandler):
    server_version = "GazeQA/0.3"
    AUTH_TOKEN = os.getenv("GAZEQA_API_TOKEN")
    SIGNING_KEY = os.getenv("GAZEQA_SIGNING_KEY")
    SIGNING_TTL = int(os.getenv("GAZEQA_SIGNING_TTL", "900"))

    @property
    def run_service(self) -> RunService:
        return self.server.run_service  # type: ignore[attr-defined]

    @property
    def ui_dir(self) -> Path:
        return self.server.ui_dir  # type: ignore[attr-defined]

    @property
    def workflow(self) -> Optional[RunWorkflow]:
        return getattr(self.server, "workflow", None)  # type: ignore[attr-defined]

    @property
    def executor(self) -> Optional[WorkflowExecutor]:
        return getattr(self.server, "workflow_executor", None)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ helpers
    def _auth_valid(self, query: str) -> bool:
        if not self.AUTH_TOKEN:
            return True
        auth_header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.AUTH_TOKEN}"
        if auth_header == expected:
            return True
        params = urllib.parse.parse_qs(query)
        return params.get("token", [None])[0] == self.AUTH_TOKEN

    def _read_json(self) -> Tuple[dict, bool]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}, False
        try:
            return json.loads(raw.decode("utf-8")), True
        except json.JSONDecodeError:
            return {}, False

    def _send_json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, resource: str) -> None:
        file_path = (self.ui_dir / resource) if resource else (self.ui_dir / "index.html")
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        content = file_path.read_bytes()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(file_path.suffix, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        # Static Lovable UI
        if path in {"/", "", "/ui", "/ui/"}:
            self._serve_static("index.html")
            return
        if path.startswith("/ui/"):
            self._serve_static(path[len("/ui/"):])
            return

        if not self._auth_valid(parsed.query):
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return

        if path == "/runs":
            self._send_paginated_runs(parsed.query)
            return

        if path == "/runs/public/download":
            self._serve_signed_artifact(parsed.query)
            return

        if path.startswith("/runs/"):
            segments = path.split("/")
            if len(segments) >= 3 and segments[2]:
                run_id = segments[2]
                if len(segments) == 3:
                    try:
                        run = self.run_service.get_run(run_id)
                    except FileNotFoundError:
                        self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    self._send_json(run)
                    return
                if len(segments) == 4 and segments[3] == "artifacts":
                    manifest = self.run_service.build_artifact_manifest(run_id)
                    self._send_artifacts(manifest, parsed.query)
                    return
                if len(segments) == 4 and segments[3] == "events":
                    self._send_run_events(run_id)
                    return
                if len(segments) == 5 and segments[3] == "events" and segments[4] == "stream":
                    self._stream_events(run_id, parsed.query)
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if not self._auth_valid(parsed.query):
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return

        if parsed.path == "/runs":
            payload, ok = self._read_json()
            if not ok:
                self._send_json({"error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                run_record = self.run_service.create_run(payload)
            except ValidationError as exc:
                self._send_json({"error": "validation_failed", "field_errors": exc.errors}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run_record, status=HTTPStatus.CREATED)
            if self.executor:
                self.executor.submit(run_record["id"])
            elif self.workflow:
                self._execute_workflow(run_record["id"])
            return

        if parsed.path.startswith("/runs/"):
            segments = parsed.path.split("/")
            if len(segments) == 4 and segments[3] == "status":
                payload, ok = self._read_json()
                if not ok or "status" not in payload:
                    self._send_json({"error": "Missing status"}, status=HTTPStatus.BAD_REQUEST)
                    return
                metadata = payload.get("metadata") if isinstance(payload, dict) else None
                self.run_service.update_status(segments[2], payload["status"], metadata)
                self._send_json({"status": "ok"})
                return
            if len(segments) == 4 and segments[3] == "checkpoints":
                payload, ok = self._read_json()
                if not ok or "checkpoint" not in payload:
                    self._send_json({"error": "Missing checkpoint"}, status=HTTPStatus.BAD_REQUEST)
                    return
                details = payload.get("details") if isinstance(payload, dict) else None
                self.run_service.record_checkpoint(segments[2], payload["checkpoint"], details)
                self._send_json({"status": "ok"})
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    # ------------------------------------------------------------------ helpers
    def _send_paginated_runs(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        offset = int(params.get("offset", [0])[0])
        limit = max(1, min(100, int(params.get("limit", [20])[0])))
        runs = self.run_service.list_runs()
        total = len(runs)
        slice_ = runs[offset : offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        self._send_json(
            {
                "runs": slice_,
                "offset": offset,
                "limit": limit,
                "total": total,
                "next_offset": next_offset,
                "previous_offset": prev_offset,
            }
        )

    def _send_artifacts(self, manifest: dict, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        offset = int(params.get("offset", [0])[0])
        limit = max(1, min(200, int(params.get("limit", [50])[0])))
        entries = manifest.get("entries", [])
        total = len(entries)
        slice_original = entries[offset : offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        processed = []
        for entry in slice_original:
            entry_copy = dict(entry)
            if self.SIGNING_KEY:
                expires = int(datetime.now(timezone.utc).timestamp()) + self.SIGNING_TTL
                signature = _sign_path(self.SIGNING_KEY, manifest.get("run_id", ""), entry_copy.get("path", ""), expires)
                entry_copy["download_url"] = (
                    f"/runs/public/download?run_id={manifest.get('run_id')}&path={urllib.parse.quote(entry_copy.get('path', ''))}"
                    f"&expires={expires}&signature={signature}"
                )
            processed.append(entry_copy)
        manifest_copy = dict(manifest)
        manifest_copy.update(
            {
                "entries": processed,
                "offset": offset,
                "limit": limit,
                "total": total,
                "next_offset": next_offset,
                "previous_offset": prev_offset,
            }
        )
        self._send_json(manifest_copy)

    def _serve_signed_artifact(self, query: str) -> None:
        if not self.SIGNING_KEY:
            self._send_json({"error": "artifact signing disabled"}, status=HTTPStatus.BAD_REQUEST)
            return
        params = urllib.parse.parse_qs(query)
        run_id = params.get("run_id", [None])[0]
        relative_path = params.get("path", [None])[0]
        signature = params.get("signature", [None])[0]
        expires = params.get("expires", [None])[0]
        if not all([run_id, relative_path, signature, expires]):
            self._send_json({"error": "missing parameters"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            expires_int = int(expires)
        except ValueError:
            self._send_json({"error": "invalid expires"}, status=HTTPStatus.BAD_REQUEST)
            return
        if expires_int < int(datetime.now(timezone.utc).timestamp()):
            self._send_json({"error": "signature expired"}, status=HTTPStatus.UNAUTHORIZED)
            return
        expected = _sign_path(self.SIGNING_KEY, run_id, relative_path, expires_int)
        if not hmac.compare_digest(expected, signature):
            self._send_json({"error": "invalid signature"}, status=HTTPStatus.UNAUTHORIZED)
            return
        try:
            artifact_path = self.run_service.get_artifact_path(run_id, relative_path)
        except ValueError:
            self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not artifact_path.exists() or not artifact_path.is_file():
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        content = artifact_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_run_events(self, run_id: str) -> None:
        try:
            events = self.run_service.get_run_events(run_id)
            history = self.run_service.get_status_history(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        payload = {
            "run_id": run_id,
            "events": events,
            "status_history": history,
        }
        self._send_json(payload)

    def _execute_workflow(self, run_id: str) -> None:
        workflow = self.workflow
        if not workflow:
            return
        try:
            workflow.execute(run_id)
        except Exception:  # pragma: no cover - background execution guard
            logger.exception("Workflow execution failed for run %s", run_id)

    def _stream_events(self, run_id: str, query: str) -> None:
        if not self._auth_valid(query):
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        try:
            history = self.run_service.get_status_history(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def write_event(event: dict) -> None:
            payload = json.dumps(event)
            self.wfile.write(f"event: status\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            for event in history:
                write_event(event)
        except BrokenPipeError:
            return

        stop_event = threading.Event()

        def listener(event: dict) -> None:
            try:
                write_event(event)
            except BrokenPipeError:
                stop_event.set()

        self.run_service.register_listener(run_id, listener)
        try:
            while not stop_event.wait(30):
                try:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    break
        finally:
            self.run_service.unregister_listener(run_id, listener)


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    storage_root: Path | str = "artifacts/runs",
    ui_root: Path | str = "webui",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RunRequestHandler)
    storage_path = Path(storage_root)
    storage_path.mkdir(parents=True, exist_ok=True)
    auth_orchestrator = build_auth_orchestrator(storage_path)
    run_service = RunService(
        storage_root=storage_path,
        auth_orchestrator=auth_orchestrator,
        invoke_auth_on_create=False,
    )
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=storage_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=storage_path))
    telemetry = RunObservability(storage_path)
    site_map_builder = partial(discover_site_map, storage_root=storage_path)
    workflow = RunWorkflow(
        run_service,
        auth_orchestrator,
        exploration_engine,
        crawler,
        telemetry=telemetry,
        site_map_builder=site_map_builder,
    )
    server.run_service = run_service  # type: ignore[attr-defined]
    server.workflow = workflow  # type: ignore[attr-defined]
    server.workflow_executor = WorkflowExecutor(workflow)  # type: ignore[attr-defined]
    ui_path = Path(ui_root)
    if not ui_path.exists():
        fallback = Path("webui")
        if fallback.exists():
            ui_path = fallback
    ui_path.mkdir(parents=True, exist_ok=True)
    server.ui_dir = ui_path  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    host = os.getenv("GAZEQA_API_HOST", "0.0.0.0")
    port = int(os.getenv("GAZEQA_API_PORT", "8000"))
    storage_root = os.getenv("GAZEQA_STORAGE_ROOT", "artifacts/runs")
    ui_root = os.getenv("GAZEQA_UI_ROOT", "webui")
    server = serve(host=host, port=port, storage_root=storage_root, ui_root=ui_root)
    print(f"GazeQA API listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
