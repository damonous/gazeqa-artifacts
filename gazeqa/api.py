"""HTTP API for GazeQA: runs, artifacts, SSE, and Lovable UI assets."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import ssl
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple

from .auth import build_auth_orchestrator
from .audit import AuditLogger
from .bfs import BFSCrawler, CrawlConfig
from .discovery import discover_site_map
from .exploration import ExplorationConfig, ExplorationEngine
from .langfuse import LangfuseClient
from .models import ValidationError
from .observability import RunObservability
from .run_service import RunService
from .security import DEFAULT_OPEN_SCOPES, SecretsManager, SigningKeySet
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
    TOKEN_REGISTRY: dict[str, dict[str, Any]] = {}

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

    @property
    def secrets_manager(self) -> Optional[SecretsManager]:
        return getattr(self.server, "secrets_manager", None)  # type: ignore[attr-defined]

    @property
    def audit_logger(self) -> Optional[AuditLogger]:
        return getattr(self.server, "audit_logger", None)  # type: ignore[attr-defined]

    @property
    def alert_webhook_token(self) -> Optional[str]:
        return getattr(self.server, "alert_webhook_token", None)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ helpers
    def _token_registry(self) -> dict[str, dict[str, Any]]:
        secrets = self.secrets_manager
        if secrets:
            registry = secrets.get_token_registry()
            if self.TOKEN_REGISTRY:
                combined = dict(registry)
                combined.update(self.TOKEN_REGISTRY)
                return combined
            return registry
        return dict(self.TOKEN_REGISTRY)

    def _signing_keys(self) -> SigningKeySet:
        secrets = self.secrets_manager
        if secrets:
            return secrets.get_signing_keys()
        key = self.SIGNING_KEY
        keys = tuple(k for k in (key,) if k)
        return SigningKeySet(primary=key, all_keys=keys)

    def _allowed_origins(self) -> set[str]:
        return getattr(self.server, "allowed_origins", set())  # type: ignore[attr-defined]

    def _cors_enabled(self) -> bool:
        return bool(self._allowed_origins())

    def _origin_allowed(self, origin: Optional[str]) -> bool:
        if not origin:
            return False
        allowed = self._allowed_origins()
        if not allowed:
            return False
        if "*" in allowed:
            return True
        return origin in allowed

    def _set_base_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _set_cors_headers(self, *, is_preflight: bool = False) -> None:
        if not self._cors_enabled():
            return
        origin = self.headers.get("Origin")
        self.send_header("Vary", "Origin")
        if origin and self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            if getattr(self.server, "cors_allow_credentials", True):  # type: ignore[attr-defined]
                self.send_header("Access-Control-Allow-Credentials", "true")
            if is_preflight:
                methods = getattr(self.server, "cors_allow_methods", "GET,POST,OPTIONS")  # type: ignore[attr-defined]
                headers = getattr(self.server, "cors_allow_headers", "Authorization,Content-Type")  # type: ignore[attr-defined]
                max_age = getattr(self.server, "cors_max_age", 600)  # type: ignore[attr-defined]
                self.send_header("Access-Control-Allow-Methods", methods)
                self.send_header("Access-Control-Allow-Headers", headers)
                self.send_header("Access-Control-Max-Age", str(max_age))

    def _client_ip(self) -> Optional[str]:
        addr = getattr(self, "client_address", None)
        if isinstance(addr, tuple) and addr:
            return str(addr[0])
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:  # type: ignore[override]
        try:
            shortmsg, longmsg = self.responses[code]
        except KeyError:
            shortmsg, longmsg = "???", "???"
        if message is None:
            message = shortmsg
        if explain is None:
            explain = longmsg
        content = (self.error_message_format % {
            "code": code,
            "message": message,
            "explain": explain,
        }).encode("utf-8", "replace")
        self.log_error("%d %s", code, message)
        self.send_response(code, message)
        self._set_base_headers()
        self._set_cors_headers()
        self.send_header("Content-Type", self.error_content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":  # pragma: no cover - mirrors BaseHTTPRequestHandler
            self.wfile.write(content)

    def _audit(
        self,
        action: str,
        *,
        status: str = "success",
        principal: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        audit = self.audit_logger
        if not audit:
            return
        try:
            audit.emit(
                action,
                status=status,
                principal=principal,
                run_id=run_id,
                metadata=metadata,
                remote_addr=self._client_ip(),
            )
        except Exception:  # pragma: no cover - do not break API on audit failure
            logger.exception("Failed to write audit log for action %s", action)

    def _auth_required(self) -> bool:
        return bool(self._token_registry())

    def _extract_token(self, query: Optional[str]) -> Optional[str]:
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token:
                return token
        if query:
            params = urllib.parse.parse_qs(query)
            token = params.get("token", [None])[0]
            if token:
                return token
        return None

    def _authenticate(self, query: Optional[str]) -> Optional[dict[str, Any]]:
        token = self._extract_token(query)
        if token is None:
            return None
        registry = self._token_registry()
        entry = registry.get(token)
        if not entry:
            return None
        principal = dict(entry)
        principal["token"] = token
        principal.setdefault("scopes", [])
        return principal

    def _require_scope(self, scope: str, query: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._auth_required():
            return {
                "organization": "default",
                "organization_slug": "default",
                "actor_role": "system",
                "scopes": sorted(DEFAULT_OPEN_SCOPES),
            }
        principal = self._authenticate(query)
        if principal is None:
            self._audit(
                "auth.failure",
                status="denied",
                metadata={"scope": scope or "*", "reason": "unauthorized"},
            )
            self._send_json({"error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return None
        scopes = {str(item) for item in principal.get("scopes", [])}
        if scope and scope not in scopes and "runs:*" not in scopes and "*" not in scopes:
            self._audit(
                "auth.failure",
                status="denied",
                principal=principal,
                metadata={"scope": scope, "reason": "insufficient_scope"},
            )
            self._send_json({"error": "forbidden", "scope": scope}, status=HTTPStatus.FORBIDDEN)
            return None
        return principal

    def _principal_can_access_org(
        self,
        principal: Optional[dict[str, Any]],
        organization_slug: str,
    ) -> bool:
        if not self._auth_required():
            return True
        if principal is None:
            return False
        scopes = {str(item) for item in principal.get("scopes", [])}
        if "runs:read:all" in scopes or "runs:*" in scopes or "*" in scopes:
            return True
        return str(principal.get("organization_slug")) == organization_slug

    def _get_run_metadata_for_principal(
        self,
        run_id: str,
        principal: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        try:
            metadata = self.run_service.get_run_metadata(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return None
        organization_slug = str(metadata.get("organization_slug", "default"))
        if not self._principal_can_access_org(principal, organization_slug):
            self._send_json({"error": "forbidden", "reason": "organization_mismatch"}, status=HTTPStatus.FORBIDDEN)
            return None
        return metadata

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
        self._set_base_headers()
        self._set_cors_headers()
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
        self._set_base_headers()
        self._set_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._set_base_headers()
        self._set_cors_headers(is_preflight=True)
        self.end_headers()

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

        if path == "/runs":
            principal = self._require_scope("runs:read", parsed.query)
            if principal is None:
                return
            self._send_paginated_runs(parsed.query, principal)
            return

        if path == "/runs/public/download":
            self._serve_signed_artifact(parsed.query)
            return

        if path.startswith("/runs/"):
            segments = path.split("/")
            if len(segments) >= 3 and segments[2]:
                run_id = segments[2]
                if len(segments) == 5 and segments[3] == "events" and segments[4] == "stream":
                    principal_stream = self._require_scope("runs:events", parsed.query)
                    if principal_stream is None:
                        return
                    if self._get_run_metadata_for_principal(run_id, principal_stream) is None:
                        return
                    self._stream_events(run_id)
                    return

                principal = self._require_scope("runs:read", parsed.query)
                if principal is None:
                    return
                if self._get_run_metadata_for_principal(run_id, principal) is None:
                    return

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
                    self._send_artifacts(manifest, parsed.query, principal)
                    return
                if len(segments) == 4 and segments[3] == "events":
                    self._send_run_events(run_id)
                    return
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/observability/alerts":
            self._handle_alert_webhook()
            return
        if parsed.path == "/runs":
            principal = self._require_scope("runs:create", parsed.query)
            if principal is None:
                return
            payload, ok = self._read_json()
            if not ok:
                self._audit(
                    "run.create",
                    status="error",
                    principal=principal,
                    metadata={"reason": "invalid_json"},
                )
                self._send_json({"error": "Invalid JSON payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload, dict):
                payload = {}
            if self._auth_required():
                requested_slug = str(payload.get("organization_slug") or "").strip()
                if requested_slug and requested_slug != principal.get("organization_slug"):
                    self._audit(
                        "run.create",
                        status="denied",
                        principal=principal,
                        metadata={"reason": "organization_mismatch", "requested": requested_slug},
                    )
                    self._send_json(
                        {
                            "error": "forbidden",
                            "reason": "organization_mismatch",
                        },
                        status=HTTPStatus.FORBIDDEN,
                    )
                    return
                payload = dict(payload)
                payload["organization_slug"] = principal.get("organization_slug", "default")
                payload["organization"] = principal.get(
                    "organization",
                    payload.get("organization") or payload.get("organization_slug") or "default",
                )
                payload["actor_role"] = principal.get("actor_role", payload.get("actor_role", "qa_runner"))
            try:
                run_record = self.run_service.create_run(payload)
            except ValidationError as exc:
                self._audit(
                    "run.create",
                    status="error",
                    principal=principal,
                    metadata={"reason": "validation_failed", "fields": list(exc.errors.keys())},
                )
                self._send_json({"error": "validation_failed", "field_errors": exc.errors}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(run_record, status=HTTPStatus.CREATED)
            self._audit(
                "run.create",
                principal=principal,
                run_id=run_record["id"],
                metadata={
                    "target_url": payload.get("target_url"),
                    "tags": payload.get("tags", []),
                },
            )
            if self.executor:
                try:
                    self.executor.submit(run_record["id"])
                except RuntimeError:
                    logger.warning("Workflow executor unavailable; skipping auto-run for %s", run_record["id"])
                    self._audit(
                        "workflow.enqueue",
                        status="error",
                        run_id=run_record["id"],
                        metadata={"reason": "executor_stopped"},
                    )
            elif self.workflow:
                self._execute_workflow(run_record["id"])
            return

        if parsed.path.startswith("/runs/"):
            segments = parsed.path.split("/")
            if len(segments) == 4 and segments[3] == "status":
                principal = self._require_scope("runs:create", parsed.query)
                if principal is None:
                    return
                if self._get_run_metadata_for_principal(segments[2], principal) is None:
                    return
                payload, ok = self._read_json()
                if not ok or "status" not in payload:
                    self._audit(
                        "run.status",
                        status="error",
                        principal=principal,
                        run_id=segments[2],
                        metadata={"reason": "missing_status"},
                    )
                    self._send_json({"error": "Missing status"}, status=HTTPStatus.BAD_REQUEST)
                    return
                metadata = payload.get("metadata") if isinstance(payload, dict) else None
                self.run_service.update_status(segments[2], payload["status"], metadata)
                self._send_json({"status": "ok"})
                self._audit(
                    "run.status",
                    principal=principal,
                    run_id=segments[2],
                    metadata={
                        "status": payload.get("status"),
                        "metadata_keys": sorted(metadata.keys()) if isinstance(metadata, dict) else [],
                    },
                )
                return
            if len(segments) == 4 and segments[3] == "checkpoints":
                principal = self._require_scope("runs:create", parsed.query)
                if principal is None:
                    return
                if self._get_run_metadata_for_principal(segments[2], principal) is None:
                    return
                payload, ok = self._read_json()
                if not ok or "checkpoint" not in payload:
                    self._audit(
                        "run.checkpoint",
                        status="error",
                        principal=principal,
                        run_id=segments[2],
                        metadata={"reason": "missing_checkpoint"},
                    )
                    self._send_json({"error": "Missing checkpoint"}, status=HTTPStatus.BAD_REQUEST)
                    return
                details = payload.get("details") if isinstance(payload, dict) else None
                self.run_service.record_checkpoint(segments[2], payload["checkpoint"], details)
                self._send_json({"status": "ok"})
                self._audit(
                    "run.checkpoint",
                    principal=principal,
                    run_id=segments[2],
                    metadata={"checkpoint": payload.get("checkpoint")},
                )
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    # ------------------------------------------------------------------ helpers
    def _send_paginated_runs(self, query: str, principal: Optional[dict[str, Any]]) -> None:
        params = urllib.parse.parse_qs(query)
        offset = int(params.get("offset", [0])[0])
        limit = max(1, min(100, int(params.get("limit", [20])[0])))
        runs = self.run_service.list_runs()
        if self._auth_required():
            runs = [
                run
                for run in runs
                if self._principal_can_access_org(
                    principal,
                    str(run.get("organization_slug", "default")),
                )
            ]
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

    def _send_artifacts(
        self,
        manifest: dict,
        query: str,
        principal: Optional[dict[str, Any]] = None,
    ) -> None:
        params = urllib.parse.parse_qs(query)
        offset = int(params.get("offset", [0])[0])
        limit = max(1, min(200, int(params.get("limit", [50])[0])))
        entries = manifest.get("entries", [])
        total = len(entries)
        slice_original = entries[offset : offset + limit]
        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset - limit >= 0 else None
        processed = []
        signing_keys = self._signing_keys()
        primary_key = signing_keys.primary
        run_id = str(manifest.get("run_id", ""))
        organization_slug = str(
            manifest.get("organization_slug")
            or (principal or {}).get("organization_slug")
            or "default"
        )
        for entry in slice_original:
            entry_copy = dict(entry)
            relative_path = entry_copy.get("path", "")
            if primary_key and run_id and relative_path:
                expires = int(datetime.now(timezone.utc).timestamp()) + self.SIGNING_TTL
                signature = _sign_path(
                    primary_key,
                    run_id,
                    organization_slug,
                    relative_path,
                    expires,
                )
                query_params = {
                    "run_id": run_id,
                    "organization_slug": organization_slug,
                    "path": relative_path,
                    "expires": str(expires),
                    "signature": signature,
                }
                entry_copy["download_url"] = "/runs/public/download?" + urllib.parse.urlencode(
                    query_params,
                    quote_via=urllib.parse.quote,
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
        self._audit(
            "artifact.list",
            principal=principal,
            run_id=run_id or None,
            metadata={"returned": len(processed), "total": total, "offset": offset},
        )

    def _serve_signed_artifact(self, query: str) -> None:
        signing_keys = self._signing_keys()
        if not signing_keys.all_keys:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "signing_disabled"},
            )
            self._send_json({"error": "artifact signing disabled"}, status=HTTPStatus.BAD_REQUEST)
            return
        params = urllib.parse.parse_qs(query)
        run_id = params.get("run_id", [None])[0]
        organization_slug = params.get("organization_slug", [None])[0]
        relative_path = params.get("path", [None])[0]
        signature = params.get("signature", [None])[0]
        expires = params.get("expires", [None])[0]
        if not all([run_id, organization_slug, relative_path, signature, expires]):
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "missing_parameters"},
            )
            self._send_json({"error": "missing parameters"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            expires_int = int(expires)
        except ValueError:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "invalid_expires", "expires": expires},
            )
            self._send_json({"error": "invalid expires"}, status=HTTPStatus.BAD_REQUEST)
            return
        now = int(datetime.now(timezone.utc).timestamp())
        if expires_int < now:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "expired_signature", "expires": expires},
            )
            self._send_json({"error": "signature expired"}, status=HTTPStatus.UNAUTHORIZED)
            return
        metadata = self.run_service.get_run_metadata(run_id)
        expected_slug = str(metadata.get("organization_slug", ""))
        if expected_slug and expected_slug != organization_slug:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "invalid_organization", "expected": expected_slug, "provided": organization_slug},
            )
            self._send_json({"error": "invalid organization"}, status=HTTPStatus.FORBIDDEN)
            return
        valid = any(
            key
            and hmac.compare_digest(
                _sign_path(key, run_id, organization_slug, relative_path, expires_int),
                signature,
            )
            for key in signing_keys.all_keys
        )
        if not valid:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "invalid_signature", "run_id": run_id},
            )
            self._send_json({"error": "invalid signature"}, status=HTTPStatus.UNAUTHORIZED)
            return
        try:
            artifact_path = self.run_service.get_artifact_path(
                run_id,
                relative_path,
                organization_slug=organization_slug,
            )
        except ValueError:
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "invalid_path", "run_id": run_id, "path": relative_path},
            )
            self._send_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not artifact_path.exists() or not artifact_path.is_file():
            self._audit(
                "artifact.download",
                status="denied",
                metadata={"reason": "not_found", "run_id": run_id, "path": relative_path},
            )
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        content = artifact_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._set_base_headers()
        self._set_cors_headers()
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)
        self._audit(
            "artifact.download",
            run_id=run_id,
            metadata={"path": relative_path, "size": len(content)},
        )

    def _handle_alert_webhook(self) -> None:
        token = self.alert_webhook_token
        auth_header = self.headers.get("Authorization", "")
        if token:
            expected = f"Bearer {token}"
            if auth_header != expected:
                self._audit(
                    "alert.received",
                    status="denied",
                    metadata={"reason": "invalid_token"},
                )
                self._send_json({"error": "forbidden"}, status=HTTPStatus.FORBIDDEN)
                return
        payload, ok = self._read_json()
        if not ok:
            self._audit(
                "alert.received",
                status="error",
                metadata={"reason": "invalid_payload"},
            )
            self._send_json({"error": "invalid payload"}, status=HTTPStatus.BAD_REQUEST)
            return
        alerts_payload = []
        if isinstance(payload, dict):
            raw_alerts = payload.get("alerts")
            if isinstance(raw_alerts, list):
                alerts_payload = raw_alerts
        summary = None
        if alerts_payload:
            first = alerts_payload[0]
            if isinstance(first, dict):
                summary = first.get("annotations", {}).get("summary") or first.get("labels", {}).get("alertname")
        metadata = {"count": len(alerts_payload)}
        if summary:
            metadata["summary"] = summary
        self._audit("alert.received", metadata=metadata)
        self._send_json({"status": "accepted"}, status=HTTPStatus.ACCEPTED)

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

    def _stream_events(self, run_id: str) -> None:
        try:
            history = self.run_service.get_status_history(run_id)
        except FileNotFoundError:
            self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        self.send_response(HTTPStatus.OK)
        self._set_base_headers()
        self._set_cors_headers()
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
    secrets_manager = SecretsManager(
        default_token=os.getenv("GAZEQA_API_TOKEN"),
        registry_json=os.getenv("GAZEQA_API_TOKEN_REGISTRY"),
        registry_file=os.getenv("GAZEQA_TOKEN_REGISTRY_FILE"),
        token_file=os.getenv("GAZEQA_API_TOKEN_FILE"),
        token_file_defaults={
            "organization": os.getenv("GAZEQA_API_TOKEN_FILE_ORGANIZATION", "default"),
            "organization_slug": os.getenv("GAZEQA_API_TOKEN_FILE_ORGANIZATION_SLUG", "default"),
            "actor_role": os.getenv("GAZEQA_API_TOKEN_FILE_ROLE", "qa_runner"),
        },
        signing_key=os.getenv("GAZEQA_SIGNING_KEY"),
        signing_key_previous=[
            key.strip()
            for key in os.getenv("GAZEQA_SIGNING_KEY_PREVIOUS", "").split(",")
            if key.strip()
        ],
        signing_key_file=os.getenv("GAZEQA_SIGNING_KEY_FILE"),
    )
    auth_orchestrator = build_auth_orchestrator(storage_path)
    run_service = RunService(
        storage_root=storage_path,
        auth_orchestrator=auth_orchestrator,
        invoke_auth_on_create=False,
    )
    exploration_engine = ExplorationEngine(ExplorationConfig(storage_root=storage_path))
    crawler = BFSCrawler(CrawlConfig(storage_root=storage_path))
    langfuse_client = LangfuseClient.from_env()
    telemetry = RunObservability(storage_root=storage_path, langfuse_client=langfuse_client)
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
    server.secrets_manager = secrets_manager  # type: ignore[attr-defined]
    server.audit_logger = AuditLogger(storage_path)  # type: ignore[attr-defined]
    if langfuse_client:
        server.langfuse_client = langfuse_client  # type: ignore[attr-defined]
    alert_token = os.getenv("GAZEQA_ALERT_WEBHOOK_TOKEN")
    if alert_token:
        server.alert_webhook_token = alert_token  # type: ignore[attr-defined]
    allowed_origins_env = os.getenv("GAZEQA_ALLOWED_ORIGINS", "")
    allowed_origins = {
        origin.strip()
        for origin in allowed_origins_env.split(",")
        if origin.strip()
    }
    server.allowed_origins = allowed_origins  # type: ignore[attr-defined]
    server.cors_allow_credentials = os.getenv("GAZEQA_CORS_ALLOW_CREDENTIALS", "true").lower() in {  # type: ignore[attr-defined]
        "1",
        "true",
        "yes",
    }
    server.cors_allow_methods = os.getenv("GAZEQA_CORS_ALLOW_METHODS", "GET,POST,OPTIONS")  # type: ignore[attr-defined]
    server.cors_allow_headers = os.getenv("GAZEQA_CORS_ALLOW_HEADERS", "Authorization,Content-Type")  # type: ignore[attr-defined]
    try:
        server.cors_max_age = int(os.getenv("GAZEQA_CORS_MAX_AGE", "600"))  # type: ignore[attr-defined]
    except ValueError:
        server.cors_max_age = 600  # type: ignore[attr-defined]
    signing_keys = secrets_manager.get_signing_keys()
    if signing_keys.primary:
        RunRequestHandler.SIGNING_KEY = signing_keys.primary
    ui_path = Path(ui_root)
    if not ui_path.exists():
        fallback = Path("webui")
        if fallback.exists():
            ui_path = fallback
    ui_path.mkdir(parents=True, exist_ok=True)
    server.ui_dir = ui_path  # type: ignore[attr-defined]
    certfile = os.getenv("GAZEQA_TLS_CERTFILE")
    keyfile = os.getenv("GAZEQA_TLS_KEYFILE")
    if certfile and keyfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile, keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _sign_path(
    key: str,
    run_id: str,
    organization_slug: str,
    relative_path: str,
    expires: int,
) -> str:
    message = f"{run_id}:{organization_slug}:{relative_path}:{expires}".encode("utf-8")
    secret = key.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


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
