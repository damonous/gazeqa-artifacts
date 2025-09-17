"""Structured observability sink for workflow telemetry (FR-011)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .telemetry import TelemetrySink


logger = logging.getLogger(__name__)


class RunObservability(TelemetrySink):
    """Aggregates telemetry into JSONL logs and metrics summaries."""

    def __init__(self, storage_root: Path | str = "artifacts/runs") -> None:
        self.storage_root = Path(storage_root)
        self._metrics_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ public
    def emit(self, event: str, payload: Dict[str, object]) -> None:
        run_id = self._extract_run_id(payload)
        if not run_id:
            logger.debug("Telemetry event %s missing run_id; dropping", event)
            return

        entry = dict(payload)
        entry.setdefault("run_id", run_id)
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        entry["event"] = event
        self._append_log(run_id, entry)

        metrics = self._metrics_cache.setdefault(run_id, {"run_id": run_id})
        self._update_metrics(metrics, entry)
        self._persist_metrics(run_id, metrics)

    # ---------------------------------------------------------------- internal
    def _append_log(self, run_id: str, entry: Dict[str, object]) -> None:
        logs_path = self._logs_path(run_id)
        logs_path.parent.mkdir(parents=True, exist_ok=True)
        with logs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _update_metrics(self, metrics: Dict[str, Any], entry: Dict[str, object]) -> None:
        event = entry.get("event", "")
        if event in {"auth.completed", "auth.skipped"}:
            stage = entry.get("stage")
            if not stage and event == "auth.skipped":
                stage = "skipped"
            metrics["auth"] = {
                "stage": stage,
                "success": bool(entry.get("success", True)),
            }
        elif event == "exploration.completed":
            metrics["exploration"] = {
                "coverage_percent": entry.get("coverage_percent"),
                "visited_count": entry.get("visited_count"),
                "skipped_count": entry.get("skipped_count"),
            }
        elif event == "crawl.completed":
            visited = _to_int(entry.get("visited_count"))
            skipped = _to_int(entry.get("skipped_count"))
            summary: Dict[str, Any] = {
                "visited_count": visited,
                "skipped_count": skipped,
            }
            total = (visited or 0) + (skipped or 0)
            if total:
                summary["health_ratio"] = round((visited or 0) / total, 4)
            metrics["crawl"] = summary
        elif event.startswith("guardrail."):
            guardrails = metrics.setdefault("guardrails", {})
            phase = str(entry.get("phase", "unknown"))
            kind = event.split(".", 1)[1]
            phase_counts = guardrails.setdefault(phase, {})
            phase_counts[kind] = int(phase_counts.get(kind, 0)) + 1
        elif event == "workflow.completed":
            metrics.setdefault("workflow", {})["completed_at"] = entry.get("timestamp")
            metrics["workflow"]["status"] = "Completed"
        elif event == "workflow.failed":
            metrics.setdefault("workflow", {})["status"] = "Failed"
            metrics["workflow"]["phase"] = entry.get("phase")
            metrics["workflow"]["error"] = entry.get("error")

    def _persist_metrics(self, run_id: str, metrics: Dict[str, Any]) -> None:
        metrics_path = self._logs_path(run_id).parent / "metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    def _logs_path(self, run_id: str) -> Path:
        return self.storage_root / run_id / "observability" / "logs.jsonl"

    @staticmethod
    def _extract_run_id(payload: Dict[str, object]) -> str:
        for key in ("run_id", "runId", "id"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return ""


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


__all__ = ["RunObservability"]
