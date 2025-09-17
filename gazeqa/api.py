"""HTTP API for GazeQA: runs, artifacts, SSE, and Lovable UI assets."""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Tuple

from .models import ValidationError
from .run_service import RunService


class RunRequestHandler(BaseHTTPRequestHandler):
    server_version = "GazeQA/0.3"
    AUTH_TOKEN = os.getenv("GAZEQA_API_TOKEN")

    @property
    def run_service(self) -> RunService:
        return self.server.run_service  # type: ignore[attr-defined]

    @property
    def ui_dir(self) -> Path:
        return self.server.ui_dir  # type: ignore[attr-defined]

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
        slice_ = entries[offset : offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        manifest_copy = dict(manifest)
        manifest_copy.update(
            {
                "entries": slice_,
                "offset": offset,
                "limit": limit,
                "total": total,
                "next_offset": next_offset,
                "previous_offset": prev_offset,
            }
        )
        self._send_json(manifest_copy)

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
    server.run_service = RunService(storage_root=storage_root)  # type: ignore[attr-defined]
    server.ui_dir = Path(ui_root)  # type: ignore[attr-defined]
    server.ui_dir.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    server = serve()
    print(f"GazeQA API listening on http://{server.server_address[0]}:{server.server_address[1]}")
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
