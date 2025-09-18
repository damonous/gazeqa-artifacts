"""Helpers for resolving run-scoped storage paths."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def resolve_run_path(storage_root: Path | str, run_id: str) -> Path:
    """Return the directory for a run, accounting for organization partitions."""

    base = Path(storage_root)
    index_path = base / "run_index.json"
    if index_path.exists():
        try:
            index: Dict[str, Dict[str, object]] = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index = {}
        entry = index.get(run_id)
        if isinstance(entry, dict):
            slug = entry.get("organization_slug")
            if isinstance(slug, str) and slug:
                return base / slug / run_id
    direct = base / run_id
    if direct.exists():
        return direct
    matches = list(base.glob(f"*/{run_id}"))
    if matches:
        return matches[0]
    return direct


__all__ = ["resolve_run_path"]
