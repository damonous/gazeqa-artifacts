"""Minimal HTTP API for CreateRun."""
from __future__ import annotations

import json
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Tuple

from .auth import build_auth_orchestrator
from .run_service import RunService, ValidationError


class RunRequestHandler(BaseHTTPRequestHandler):
    server_version = "GazeQA/0.1"

    @property
    def run_service(self) -> RunService:
        return self.server.run_service  # type: ignore[attr-defined]

    def _read_json(self) -> Tuple[dict, bool]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")), True
        except json.JSONDecodeError:
            return {}, False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/runs":
            self._send_paginated_runs(parsed.query)
            return
        if parsed.path.startswith("/runs"):
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) == 2:
                run_id = parts[1]
                try:
                    run = self.run_service.get_run(run_id)
                except FileNotFoundError:
                    self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(run)
                return
            if len(parts) == 3 and parts[2] == "artifacts":
                run_id = parts[1]
                try:
                    manifest = self.run_service.build_artifact_manifest(run_id)
                except FileNotFoundError:
                    self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json(manifest)
                return
            if len(parts) == 3 and parts[2] == "events":
                run_id = parts[1]
                self._send_run_events(run_id)
                return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/runs":
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

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - keep quiet during tests
        return

    def _send_json(self, data: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        slice_ = runs[offset : offset + limit]
        total = len(runs)
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        self._send_json(
            {
                "runs": slice_,
                "offset": offset,
                "limit": limit,
                "next_offset": next_offset,
                "previous_offset": prev_offset,
                "total": total,
            }
        )

    def _send_run_events(self, run_id: str) -> None:
        try:
            events = self.run_service.get_run_events(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json({"run_id": run_id, "events": events})


def serve(host: str = "127.0.0.1", port: int = 8000, storage_root: Path | str = "artifacts/runs") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RunRequestHandler)
    orchestrator = build_auth_orchestrator(Path(storage_root))
    server.run_service = RunService(  # type: ignore[attr-defined]
        storage_root=storage_root,
        auth_orchestrator=orchestrator,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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
