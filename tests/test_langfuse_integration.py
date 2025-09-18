from __future__ import annotations

from pathlib import Path

from gazeqa.observability import RunObservability


class StubLangfuse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def emit(self, event: str, payload: dict) -> None:
        self.calls.append((event, payload))


def test_run_observability_forwards_langfuse(tmp_path: Path) -> None:
    stub = StubLangfuse()
    telemetry = RunObservability(storage_root=tmp_path, langfuse_client=stub)
    telemetry.emit("workflow.completed", {"run_id": "RUN-TEST-123", "timestamp": "2025-01-01T00:00:00Z"})
    assert stub.calls
    event, payload = stub.calls[0]
    assert event == "workflow.completed"
    assert payload["run_id"] == "RUN-TEST-123"
