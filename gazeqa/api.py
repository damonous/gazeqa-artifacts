"""HTTP API and Lovable dashboard endpoints for GazeQA."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple

from .auth import build_auth_orchestrator
from .models import ValidationError
from .run_service import RunService


class RunRequestHandler(BaseHTTPRequestHandler):
    server_version = "GazeQA/0.3"
    AUTH_TOKEN = os.getenv("GAZEQA_API_TOKEN")

    # ------------------------------------------------------------------ helpers
    @property
    def run_service(self) -> RunService:
        return self.server.run_service  # type: ignore[attr-defined]

    @property
    def ui_dir(self) -> Optional[Path]:
        return getattr(self.server, "ui_dir", None)  # type: ignore[attr-defined]

    def _parse(self) -> Tuple[str, str, str]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path, parsed.query, parsed.fragment

    def _is_authorized(self, query: str) -> bool:
        if not self.AUTH_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {self.AUTH_TOKEN}":
            return True
        params = urllib.parse.parse_qs(query)
        supplied = params.get("token", [None])[0]
        return supplied == self.AUTH_TOKEN

    def _send_json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ static UI
    def _serve_static(self, resource: str) -> bool:
        ui_dir = self.ui_dir
        if not ui_dir:
            return False
        resource = resource or "dashboard.html"
        file_path = ui_dir / resource
        if not file_path.exists() or not file_path.is_file():
            return False
        content = file_path.read_bytes()
        suffix = file_path.suffix.lower()
        if suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif suffix == ".css":
            content_type = "text/css; charset=utf-8"
        else:
            content_type = "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        return True

    # ------------------------------------------------------------------ requests
    def do_GET(self) -> None:  # noqa: N802
        path, query, _ = self._parse()

        if path in {"/", "", "/lovable", "/lovable/"}:
            if self._serve_static("dashboard.html"):
                return
        if path.startswith("/lovable/"):
            if self._serve_static(path[len("/lovable/") :]):
                return
        if path.startswith("/ui/"):
            if self._serve_static(path[len("/ui/") :]):
                return

        if not self._is_authorized(query):
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return

        if path == "/runs":
            self._send_paginated_runs(query)
            return

        if path.startswith("/runs/"):
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 2:
                run_id = segments[1]
                if len(segments) == 2:
                    self._send_run_manifest(run_id)
                    return
                if len(segments) == 3 and segments[2] == "artifacts":
                    self._send_artifacts(run_id, query)
                    return
                if len(segments) == 3 and segments[2] == "events":
                    self._send_run_events(run_id)
                    return
                if len(segments) == 4 and segments[2] == "events" and segments[3] == "stream":
                    self._stream_run_events(run_id)
                    return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        path, query, _ = self._parse()
        if not self._is_authorized(query):
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        if path != "/runs":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
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

    # ------------------------------------------------------------------ helpers
    def _read_json(self) -> Tuple[dict, bool]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), True
        except json.JSONDecodeError:
            return {}, False

    def _send_run_manifest(self, run_id: str) -> None:
        try:
            manifest = self.run_service.get_run(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(manifest)

    def _send_paginated_runs(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        try:
            offset = max(0, int(params.get("offset", [0])[0]))
        except ValueError:
            offset = 0
        try:
            limit = int(params.get("limit", [20])[0])
        except ValueError:
            limit = 20
        limit = max(1, min(limit, 100))
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

    def _send_artifacts(self, run_id: str, query: str) -> None:
        try:
            manifest = self.run_service.build_artifact_manifest(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        params = urllib.parse.parse_qs(query)
        try:
            offset = max(0, int(params.get("offset", [0])[0]))
        except ValueError:
            offset = 0
        try:
            limit = int(params.get("limit", [100])[0])
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 500))
        entries = manifest.get("entries", [])
        total = len(entries)
        slice_ = entries[offset : offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        manifest = dict(manifest)
        manifest.update(
            {
                "entries": slice_,
                "offset": offset,
                "limit": limit,
                "total": total,
                "next_offset": next_offset,
                "previous_offset": prev_offset,
            }
        )
        self._send_json(manifest)

    def _send_run_events(self, run_id: str) -> None:
        events = self.run_service.get_run_events(run_id)
        self._send_json({"run_id": run_id, "events": events})

    def _stream_run_events(self, run_id: str) -> None:
        try:
            existing = self.run_service.get_run_events(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = False

        finished = threading.Event()
        lock = threading.Lock()

        def write_event(event: dict) -> None:
            message = f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
            with lock:
                self.wfile.write(message)
                self.wfile.flush()

        try:
            for event in existing:
                write_event(event)
        except (BrokenPipeError, ConnectionError, OSError):
            finished.set()

        def listener(event: dict) -> None:
            if finished.is_set():
                return
            try:
                write_event(event)
            except (BrokenPipeError, ConnectionError, OSError):
                finished.set()

        self.run_service.register_listener(run_id, listener)
        try:
            while not finished.wait(10):
                try:
                    with lock:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    break
        finally:
            self.run_service.unregister_listener(run_id, listener)
            finished.set()


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    storage_root: Path | str = "artifacts/runs",
    ui_root: Path | str = "lovable",
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RunRequestHandler)
    orchestrator = build_auth_orchestrator(Path(storage_root))
    server.run_service = RunService(  # type: ignore[attr-defined]
        storage_root=storage_root,
        auth_orchestrator=orchestrator,
    )
    ui_path = Path(ui_root)
    if ui_path.exists():
        server.ui_dir = ui_path  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:  # pragma: no cover
    server = serve()
    print(f"GazeQA API listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
