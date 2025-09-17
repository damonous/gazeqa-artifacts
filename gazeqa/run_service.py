"""Run service handles CreateRun lifecycle."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TYPE_CHECKING

from .artifacts import ArtifactManifestBuilder
from .models import CreateRunPayload, ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from .auth import AuthenticationOrchestrator


class RunService:
    """Persists runs locally for prototype purposes."""

    def __init__(
        self,
        storage_root: Path | str = "artifacts/runs",
        auth_orchestrator: "AuthenticationOrchestrator" | None = None,
    ) -> None:
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.auth_orchestrator = auth_orchestrator

    def create_run(self, payload_dict: Dict[str, object]) -> Dict[str, object]:
        payload = CreateRunPayload.from_dict(payload_dict)
        run_id = self._generate_run_id()
        run_record = {
            "id": run_id,
            "target_url": payload.target_url,
            "credentials": {
                "username": payload.credentials.username,
                "secret_ref": payload.credentials.secret_ref,
            },
            "budgets": {
                "time_budget_minutes": payload.budgets.time_budget_minutes,
                "page_budget": payload.budgets.page_budget,
            },
            "storage_profile": payload.storage_profile,
            "tags": payload.tags,
            "status": "Pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        auth_result: Optional[dict] = None
        run_dir = self.storage_root / run_id

        if self.auth_orchestrator and not payload.credentials.is_empty():
            auth_result = self.auth_orchestrator.authenticate(run_id, payload.credentials)
            run_record["auth"] = {
                "stage": auth_result.get("stage"),
                "success": auth_result.get("success"),
                "storage_state_path": self._to_relative_path(
                    auth_result.get("storage_state_path"), run_dir
                ),
            }

        self._persist_run(run_id, run_dir, run_record, auth_result)
        self._append_event(
            run_dir,
            {
                "event": "run.created",
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": run_record["status"],
            },
        )
        return run_record

    def get_run(self, run_id: str) -> Dict[str, object]:
        run_dir = self.storage_root / run_id
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Run {run_id} not found")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_runs(self) -> List[str]:
        return sorted(p.name for p in self.storage_root.iterdir() if p.is_dir())

    def build_artifact_manifest(self, run_id: str) -> Dict[str, object]:
        builder = ArtifactManifestBuilder(self.storage_root)
        return builder.build(run_id)

    def get_run_events(self, run_id: str) -> List[Dict[str, object]]:
        run_dir = self.storage_root / run_id
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            raise FileNotFoundError(f"Run {run_id} events not found")
        events: List[Dict[str, object]] = []
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _generate_run_id(self) -> str:
        return f"RUN-{uuid.uuid4().hex[:12].upper()}"

    def _persist_run(
        self,
        run_id: str,
        run_dir: Path,
        run_record: Dict[str, object],
        auth_result: Optional[dict],
    ) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = run_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(run_record, indent=2), encoding="utf-8")

        summary: Dict[str, object] = {
            "run_id": run_id,
            "env": "dev",
            "tests": [],
            "criteria": [],
            "intake": {
                "status": "Pending",
                "created_at": run_record["created_at"],
            },
        }

        if auth_result:
            summary["auth"] = {
                "stage": auth_result.get("stage"),
                "success": auth_result.get("success"),
                "storage_state_path": self._to_relative_path(
                    auth_result.get("storage_state_path"), run_dir
                ),
                "evidence": self._normalize_evidence(
                    auth_result.get("evidence", []), run_dir
                ),
                "metadata": auth_result.get("metadata", {}),
            }

        summary_path = run_dir / "run_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def _append_event(self, run_dir: Path, event: Dict[str, object]) -> None:
        events_path = run_dir / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    @staticmethod
    def _to_relative_path(path_value: Optional[str], run_dir: Path) -> Optional[str]:
        if not path_value:
            return None
        try:
            path = Path(path_value)
            return str(path.relative_to(run_dir))
        except ValueError:
            return str(path_value)

    @staticmethod
    def _normalize_evidence(paths: Iterable[str], run_dir: Path) -> list[str]:
        normalized: list[str] = []
        for item in paths:
            candidate = Path(item)
            try:
                normalized.append(str(candidate.relative_to(run_dir)))
            except ValueError:
                normalized.append(str(candidate))
        return normalized


__all__ = ["RunService", "ValidationError"]
