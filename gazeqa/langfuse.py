"""Langfuse telemetry client for FR-011."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class LangfuseClient:
    """Minimal client for forwarding spans to Langfuse."""

    def __init__(
        self,
        base_url: str,
        public_key: str,
        secret_key: str,
        *,
        environment: str = "development",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.public_key = public_key
        self.secret_key = secret_key
        self.environment = environment
        self.timeout_seconds = timeout_seconds

    # -------------------------------------------------------------- construction
    @classmethod
    def from_env(cls) -> Optional[LangfuseClient]:
        secret = os.getenv("LANGFUSE_SECRET_KEY")
        public = os.getenv("LANGFUSE_PUBLIC_KEY")
        if not secret or not public:
            return None
        base_url = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
        environment = os.getenv("LANGFUSE_ENVIRONMENT", "development")
        timeout = float(os.getenv("LANGFUSE_TIMEOUT_SECONDS", "5"))
        return cls(base_url, public, secret, environment=environment, timeout_seconds=timeout)

    # -------------------------------------------------------------------- public
    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        """Send a telemetry event as a Langfuse span."""

        trace_id = _extract_trace_id(payload)
        body = {
            "traceId": trace_id,
            "name": event,
            "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "environment": self.environment,
            "metadata": payload,
        }
        url = f"{self.base_url}/api/public/ingest"
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "X-Langfuse-Public-Key": self.public_key,
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(url, json=body, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - best effort logging
            logger.warning("Failed to emit Langfuse span for %s: %s", event, exc)


def _extract_trace_id(payload: Dict[str, Any]) -> str:
    for key in ("run_id", "runId", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


__all__ = ["LangfuseClient"]
