"""Artifact packaging utilities for FR-008."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable


@dataclass(slots=True)
class ArtifactEntry:
    path: Path
    size: int
    checksum: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "size": self.size,
            "sha256": self.checksum,
        }


class ArtifactManifestBuilder:
    """Builds artifacts/index.json for a run directory."""

    def __init__(self, storage_root: Path | str = Path("artifacts/runs")) -> None:
        self.storage_root = Path(storage_root)

    def build(self, run_id: str, include_patterns: Iterable[str] | None = None) -> Dict[str, object]:
        run_dir = self.storage_root / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        include = set(include_patterns or [])
        entries: list[ArtifactEntry] = []
        for path in run_dir.rglob("*"):
            if path.is_dir():
                continue
            relative = path.relative_to(run_dir)
            if include and not any(relative.as_posix().startswith(pattern) for pattern in include):
                continue
            entries.append(self._make_entry(path, relative))
        from datetime import datetime, timezone
        manifest = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": [entry.to_dict() for entry in sorted(entries, key=lambda e: e.path.as_posix())],
        }
        self._write_manifest(run_dir, manifest)
        return manifest

    def _make_entry(self, path: Path, relative: Path) -> ArtifactEntry:
        size = path.stat().st_size
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        return ArtifactEntry(relative, size, checksum)

    def _write_manifest(self, run_dir: Path, manifest: Dict[str, object]) -> None:
        manifest_dir = run_dir / "artifacts"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "index.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


__all__ = ["ArtifactManifestBuilder", "ArtifactEntry"]
