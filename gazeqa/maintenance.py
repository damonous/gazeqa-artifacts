"""Maintenance utilities for run storage."""
from __future__ import annotations

from pathlib import Path

from .run_service import RunService


def rebuild_run_index(storage_root: Path | str, *, move_legacy: bool = False) -> dict[str, dict[str, object]]:
    """Rebuild run_index.json and optionally relocate legacy runs."""

    service = RunService(storage_root=storage_root, invoke_auth_on_create=False)
    return service.rebuild_index(move_legacy=move_legacy)


__all__ = ["rebuild_run_index"]
