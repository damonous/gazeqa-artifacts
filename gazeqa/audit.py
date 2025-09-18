"""Audit logging utilities for FR-017."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes tamper-evident JSONL audit records."""

    def __init__(self, storage_root: Path | str, filename: str = "audit.log.jsonl") -> None:
        self._path = Path(storage_root) / "_audit" / filename
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def emit(
        self,
        action: str,
        *,
        status: str = "success",
        principal: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        remote_addr: Optional[str] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "status": status,
        }
        if run_id:
            entry["run_id"] = run_id
        if principal:
            actor_role = principal.get("actor_role")
            organization_slug = principal.get("organization_slug")
            if actor_role:
                entry["actor_role"] = actor_role
            if organization_slug:
                entry["organization_slug"] = organization_slug
            token = principal.get("token")
            if isinstance(token, str) and token:
                entry["token_hash"] = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        if metadata:
            entry["metadata"] = metadata
        if remote_addr:
            entry["remote_addr"] = remote_addr
        payload = json.dumps(entry, sort_keys=True)
        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(payload + "\n")
            except OSError as exc:
                logger.error("Failed to write audit log %s: %s", self._path, exc)


__all__ = ["AuditLogger"]
