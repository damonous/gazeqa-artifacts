"""Shared telemetry interfaces for structured observability."""
from __future__ import annotations

from typing import Dict


class TelemetrySink:
    """Base class for sinks that consume structured telemetry events."""

    def emit(self, event: str, payload: Dict[str, object]) -> None:  # pragma: no cover - interface only
        raise NotImplementedError


class NoOpTelemetry(TelemetrySink):
    """Telemetry sink that ignores all events."""

    def emit(self, event: str, payload: Dict[str, object]) -> None:  # pragma: no cover - intentionally empty
        return


__all__ = ["TelemetrySink", "NoOpTelemetry"]

