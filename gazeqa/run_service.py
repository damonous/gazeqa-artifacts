"""Run service handles CreateRun lifecycle."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, TYPE_CHECKING

from .artifacts import ArtifactManifestBuilder
from .path_utils import resolve_run_path
from .models import CreateRunPayload, ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from .auth import AuthenticationOrchestrator


class RunService:
    """Persists runs locally for prototype purposes."""

    def __init__(
        self,
        storage_root: Path | str = "artifacts/runs",
        auth_orchestrator: "AuthenticationOrchestrator" | None = None,
        *,
        invoke_auth_on_create: bool = True,
    ) -> None:
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.storage_root / "run_index.json"
        self.auth_orchestrator = auth_orchestrator
        self.invoke_auth_on_create = invoke_auth_on_create
        self.status_listeners: Dict[str, List[Callable[[dict], None]]] = {}

    def create_run(self, payload_dict: Dict[str, object]) -> Dict[str, object]:
        payload = CreateRunPayload.from_dict(payload_dict)
        run_id = self._generate_run_id()
        run_dir = self._run_dir(payload.organization_slug, run_id)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()

        run_record: Dict[str, object] = {
            "id": run_id,
            "status": "Pending",
            "status_history": [
                {"status": "Pending", "timestamp": timestamp}
            ],
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
            "created_at": timestamp,
            "organization": payload.organization,
            "organization_slug": payload.organization_slug,
            "actor_role": payload.actor_role,
        }

        auth_result: Optional[dict] = None
        if (
            self.invoke_auth_on_create
            and self.auth_orchestrator
            and not payload.credentials.is_empty()
        ):
            auth_result = self.auth_orchestrator.authenticate(
                run_id,
                payload.credentials,
                run_dir=run_dir,
                organization_slug=payload.organization_slug,
            )
            status = "Authenticated" if auth_result.get("success") else "AuthFailed"
            run_record["status"] = status
            run_record.setdefault("status_history", []).append(
                {"status": status, "timestamp": datetime.now(timezone.utc).isoformat()}
            )

        # Transition to running state once persisted
        run_record["status"] = "Running"
        run_record.setdefault("status_history", []).append(
            {"status": "Running", "timestamp": datetime.now(timezone.utc).isoformat()}
        )

        self._persist_run(run_id, run_dir, run_record, auth_result)
        event = {
            "event": "run.created",
            "run_id": run_id,
            "status": run_record["status"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._append_event(run_dir, event)
        self._append_status_history(run_dir, event)
        self._notify_listeners(run_id, event)
        self._update_index(
            run_id,
            {
                "organization": payload.organization,
                "organization_slug": payload.organization_slug,
                "actor_role": payload.actor_role,
            },
        )
        self.log_audit_event(
            run_id,
            "run.create",
            {
                "status": run_record["status"],
                "organization_slug": payload.organization_slug,
            },
        )
        return run_record

    def get_run(self, run_id: str) -> Dict[str, object]:
        run_dir = self._resolve_run_dir(run_id)
        manifest_path = run_dir / "run_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Run {run_id} not found")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_runs(self) -> List[Dict[str, object]]:
        index = self._read_index()
        entries: List[Dict[str, object]] = []
        for run_id, metadata in index.items():
            entry = {"id": run_id}
            if isinstance(metadata, dict):
                entry.update(metadata)
            entries.append(entry)
        if not entries:
            for manifest in sorted(self.storage_root.glob("**/run_manifest.json")):
                run_dir = manifest.parent
                run_id = run_dir.name
                if any(item.get("id") == run_id for item in entries):
                    continue
                org_dir = run_dir.parent
                organization_slug = org_dir.name if org_dir != self.storage_root else "default"
                entries.append(
                    {
                        "id": run_id,
                        "organization_slug": organization_slug,
                        "organization": organization_slug,
                    }
                )
        return sorted(entries, key=lambda item: item.get("id", ""))

    def build_artifact_manifest(self, run_id: str) -> Dict[str, object]:
        metadata = self._get_index_entry(run_id)
        organization_slug = metadata.get("organization_slug") if metadata else None
        builder = ArtifactManifestBuilder(self.storage_root)
        manifest = builder.build(run_id, organization_slug=organization_slug)
        if organization_slug:
            manifest.setdefault("organization_slug", organization_slug)
        return manifest

    def get_artifact_path(
        self,
        run_id: str,
        relative_path: str,
        *,
        organization_slug: str | None = None,
    ) -> Path:
        if organization_slug:
            metadata = self.get_run_metadata(run_id)
            expected = metadata.get("organization_slug")
            if expected and expected != organization_slug:
                raise ValueError("organization context mismatch")
            run_dir = self._run_dir(organization_slug, run_id)
            if not run_dir.exists() or not run_dir.is_dir():
                run_dir = self._resolve_run_dir(run_id)
        else:
            run_dir = self._resolve_run_dir(run_id)
        candidate = (run_dir / relative_path).resolve()
        base = run_dir.resolve()
        if not str(candidate).startswith(str(base)):
            raise ValueError("invalid artifact path")
        return candidate

    def get_run_directory(self, run_id: str) -> Path:
        return self._resolve_run_dir(run_id)

    def get_run_metadata(self, run_id: str) -> Dict[str, object]:
        metadata = self._get_index_entry(run_id)
        if metadata:
            return metadata
        manifest = self.get_run(run_id)
        return {
            "organization": manifest.get("organization", "default"),
            "organization_slug": manifest.get("organization_slug", "default"),
            "actor_role": manifest.get("actor_role", "qa_runner"),
        }

    def get_status_history(self, run_id: str) -> List[Dict[str, object]]:
        run_dir = self._resolve_run_dir(run_id)
        history_path = run_dir / "status_history.json"
        if history_path.exists():
            return json.loads(history_path.read_text(encoding="utf-8"))
        manifest = self.get_run(run_id)
        history = manifest.get("status_history")
        if history:
            return history  # type: ignore[return-value]
        return [
            {
                "status": manifest.get("status", "Pending"),
                "timestamp": manifest.get("created_at"),
            }
        ]

    def record_checkpoint(
        self,
        run_id: str,
        checkpoint: str,
        details: Optional[Dict[str, object]] = None,
    ) -> None:
        run_dir = self._resolve_run_dir(run_id)
        path = run_dir / "temporal" / "checkpoints.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": run_id,
            "checkpoint": checkpoint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            payload.update(details)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def rebuild_index(self, *, move_legacy: bool = False) -> Dict[str, Dict[str, object]]:
        """Rebuild run_index.json and optionally migrate legacy directories."""

        index: Dict[str, Dict[str, object]] = {}
        manifests = sorted(self.storage_root.glob("**/run_manifest.json"))
        for manifest_path in manifests:
            run_dir = manifest_path.parent
            run_id = run_dir.name
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            organization_slug = str(manifest.get("organization_slug") or "default").strip() or "default"
            organization = str(manifest.get("organization") or organization_slug)
            actor_role = str(manifest.get("actor_role") or "qa_runner")
            if move_legacy:
                expected_dir = self._run_dir(organization_slug, run_id)
                if not expected_dir.exists() and run_dir != expected_dir:
                    expected_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(run_dir), str(expected_dir))
                    run_dir = expected_dir
                elif run_dir != expected_dir and expected_dir.exists():
                    run_dir = expected_dir
            index[run_id] = {
                "organization": organization,
                "organization_slug": organization_slug,
                "actor_role": actor_role,
            }
        self._write_index(index)
        return index

    def update_status(
        self,
        run_id: str,
        status: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        run_dir = self._resolve_run_dir(run_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        history = self.get_status_history(run_id)
        history.append({"status": status, "timestamp": timestamp})
        (run_dir / "status_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

        manifest = self.get_run(run_id)
        manifest["status"] = status
        manifest.setdefault("status_history", history)
        if metadata:
            manifest.setdefault("status_metadata", {}).update(metadata)
        (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        summary_path = run_dir / "run_summary.json"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["status"] = status
            summary["status_history"] = history
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        event = {
            "event": "run.status",
            "run_id": run_id,
            "status": status,
            "timestamp": timestamp,
        }
        if metadata:
            event["metadata"] = metadata
        self._append_event(run_dir, event)
        self._append_status_history(run_dir, event)
        self._notify_listeners(run_id, event)

    def register_listener(self, run_id: str, callback: Callable[[dict], None]) -> None:
        self.status_listeners.setdefault(run_id, []).append(callback)

    def unregister_listener(self, run_id: str, callback: Callable[[dict], None]) -> None:
        listeners = self.status_listeners.get(run_id)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            return
        if not listeners:
            self.status_listeners.pop(run_id, None)

    def get_run_events(self, run_id: str) -> List[Dict[str, object]]:
        run_dir = self._resolve_run_dir(run_id)
        events_path = run_dir / "events.jsonl"
        if not events_path.exists():
            return []
        events: List[Dict[str, object]] = []
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
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
            "status": run_record.get("status"),
            "status_history": run_record.get("status_history", []),
            "organization": run_record.get("organization"),
            "organization_slug": run_record.get("organization_slug"),
            "actor_role": run_record.get("actor_role"),
        }
        summary_path = run_dir / "run_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        history_path = run_dir / "status_history.json"
        history_path.write_text(json.dumps(run_record.get("status_history", []), indent=2), encoding="utf-8")

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
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def _append_event(self, run_dir: Path, event: Dict[str, object]) -> None:
        events_path = run_dir / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def _append_status_history(self, run_dir: Path, event: Dict[str, object]) -> None:
        history_path = run_dir / "status_history.json"
        try:
            history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
        except json.JSONDecodeError:
            history = []
        status = event.get("status")
        timestamp = event.get("timestamp")
        if status is None or timestamp is None:
            return
        entry = {"status": status, "timestamp": timestamp}
        if history and history[-1].get("status") == status:
            return
        history.append(entry)
        history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def _notify_listeners(self, run_id: str, event: dict) -> None:
        for callback in list(self.status_listeners.get(run_id, [])):
            try:
                callback(event)
            except Exception:  # pragma: no cover
                continue

    def log_audit_event(
        self,
        run_id: str,
        event: str,
        details: Dict[str, object] | None = None,
    ) -> None:
        run_dir = self._resolve_run_dir(run_id)
        audit_dir = run_dir / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, object] = {
            "event": event,
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            payload.update(_safe_metadata(details))
        with (audit_dir / "audit.log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def _run_dir(self, organization_slug: str | None, run_id: str) -> Path:
        slug = organization_slug or "default"
        return self.storage_root / slug / run_id

    def _read_index(self) -> Dict[str, Dict[str, object]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_index(self, index: Dict[str, Dict[str, object]]) -> None:
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    def _update_index(self, run_id: str, metadata: Dict[str, object]) -> None:
        index = self._read_index()
        index[run_id] = metadata
        self._write_index(index)

    def _get_index_entry(self, run_id: str) -> Dict[str, object]:
        index = self._read_index()
        entry = index.get(run_id)
        return dict(entry) if isinstance(entry, dict) else {}

    def _resolve_run_dir(self, run_id: str) -> Path:
        candidate = resolve_run_path(self.storage_root, run_id)
        if candidate.exists() and candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"Run {run_id} not found")


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
    def _normalize_evidence(paths: Iterable[str], run_dir: Path) -> List[str]:
        normalized: List[str] = []
        for item in paths:
            candidate = Path(item)
            try:
                normalized.append(str(candidate.relative_to(run_dir)))
            except ValueError:
                normalized.append(str(candidate))
        return normalized


def _safe_metadata(metadata: Dict[str, object]) -> Dict[str, object]:
    safe: Dict[str, object] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


__all__ = ["RunService", "ValidationError"]
