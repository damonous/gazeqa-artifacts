"""Workflow orchestration with Temporal-style retries for FR-012."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .bfs import BFSCrawler, CrawlResult
from .models import CreateRunPayload
from .telemetry import TelemetrySink, NoOpTelemetry
from .exploration import ExplorationEngine, ExplorationResult, PageDescriptor
from .models import CreateRunPayload
from .observability import RunObservability
from .run_service import RunService
from .telemetry import NoOpTelemetry, TelemetrySink


logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """Base exception for workflow failures."""


class RetryableWorkflowError(WorkflowError):
    """Raised when a workflow activity should be retried."""


@dataclass(slots=True)
class RetryPolicy:
    """Defines retry behaviour for workflow activities."""

    max_attempts: int = 3
    backoff_seconds: Sequence[float] = (0.0, 0.0, 0.0)

    def sleep_for(self, attempt: int) -> float:
        if not self.backoff_seconds:
            return 0.0
        index = min(max(0, attempt - 1), len(self.backoff_seconds) - 1)
        return float(self.backoff_seconds[index])


class TemporalTaskRunner:
    """Lightweight simulation of Temporal retries and checkpointing."""

    def __init__(self, run_service: RunService, default_policy: RetryPolicy | None = None) -> None:
        self.run_service = run_service
        self.default_policy = default_policy or RetryPolicy()

    def run_activity(
        self,
        run_id: str,
        name: str,
        func: Callable[[], Any],
        *,
        policy: RetryPolicy | None = None,
        attempt_metadata: Dict[str, Any] | None = None,
        success_metadata_fn: Callable[[Any], Dict[str, Any]] | None = None,
    ) -> Any:
        policy = policy or self.default_policy
        last_error: Optional[BaseException] = None
        for attempt in range(1, policy.max_attempts + 1):
            attempt_payload = {"attempt": attempt}
            if attempt_metadata:
                attempt_payload.update(_safe_metadata(attempt_metadata))
            self.run_service.record_checkpoint(run_id, f"{name}.attempt", attempt_payload)
            start_time = time.monotonic()
            try:
                result = func()
            except RetryableWorkflowError as exc:
                last_error = exc
                retry_payload = {
                    "attempt": attempt,
                    "error": str(exc),
                    "exception": exc.__class__.__name__,
                }
                self.run_service.record_checkpoint(run_id, f"{name}.retry", retry_payload)
                if attempt >= policy.max_attempts:
                    failure_payload = retry_payload.copy()
                    self.run_service.record_checkpoint(run_id, f"{name}.failed", failure_payload)
                    raise
                sleep_for = policy.sleep_for(attempt + 1)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                continue
            except Exception as exc:
                last_error = exc
                failure_payload = {
                    "attempt": attempt,
                    "error": str(exc),
                    "exception": exc.__class__.__name__,
                }
                self.run_service.record_checkpoint(run_id, f"{name}.failed", failure_payload)
                raise
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            success_payload = {"attempt": attempt, "duration_ms": duration_ms}
            if success_metadata_fn:
                try:
                    extra = success_metadata_fn(result)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.exception("success_metadata_fn failed for %s", name)
                    extra = {"metadata_error": str(exc)}
                success_payload.update(_safe_metadata(extra))
            self.run_service.record_checkpoint(run_id, f"{name}.succeeded", success_payload)
            return result
        if last_error:
            raise last_error
        raise WorkflowError(f"Activity {name} did not complete but no error captured")


def _safe_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


class RunWorkflow:
    """Coordinates auth, exploration, and crawl phases with retry semantics."""

    def __init__(
        self,
        run_service: RunService,
        auth_orchestrator: Any,
        exploration_engine: ExplorationEngine,
        crawler: BFSCrawler,
        *,
        retry_policy: RetryPolicy | None = None,
        telemetry: Optional["TelemetrySink"] = None,
        site_map_builder: Optional[
            Callable[[CreateRunPayload], Tuple[List[PageDescriptor], Dict[str, List[PageDescriptor]]]]
        ] = None,
    ) -> None:
        self.run_service = run_service
        self.auth_orchestrator = auth_orchestrator
        self.exploration_engine = exploration_engine
        self.crawler = crawler
        self.temporal = TemporalTaskRunner(run_service, retry_policy)
        self.telemetry = telemetry or RunObservability(run_service.storage_root)
        self.site_map_builder = site_map_builder
        self._bind_component_telemetry()

    def start(
        self,
        payload_dict: Dict[str, Any],
        *,
        site_map: Iterable[PageDescriptor] | None = None,
        adjacency: Dict[str, List[PageDescriptor]] | None = None,
    ) -> Dict[str, Any]:
        run_record = self.run_service.create_run(payload_dict)
        run_id = run_record["id"]
        return self.execute(run_id, site_map=site_map, adjacency=adjacency)

    def execute(
        self,
        run_id: str,
        *,
        site_map: Iterable[PageDescriptor] | None = None,
        adjacency: Dict[str, List[PageDescriptor]] | None = None,
    ) -> Dict[str, Any]:
        manifest = self.run_service.get_run(run_id)
        payload = CreateRunPayload.from_dict(manifest)
        resolved_site_map, resolved_adjacency = self._resolve_site_map(site_map, adjacency, payload)
        self._record_checkpoint(run_id, "workflow.started", {"target_url": payload.target_url})
        self._emit("workflow.started", {"run_id": run_id, "target_url": payload.target_url})
        phase = "initializing"
        try:
            phase = "auth"
            if payload.credentials.is_empty() or self.auth_orchestrator is None:
                reason = "no_credentials" if payload.credentials.is_empty() else "orchestrator_unavailable"
                auth_result = {"success": True, "stage": "skipped", "reason": reason}
                self.run_service.update_status(run_id, "AuthSkipped", {"phase": phase, "reason": reason})
                self._record_checkpoint(
                    run_id,
                    "auth.skipped",
                    {"reason": reason},
                )
                self._emit(
                    "auth.skipped",
                    {"run_id": run_id, "reason": reason},
                )
            else:
                self.run_service.update_status(run_id, "AuthInProgress", {"phase": phase})
                auth_result = self.temporal.run_activity(
                    run_id,
                    "auth",
                    lambda: self._execute_auth(run_id, payload),
                    attempt_metadata={"phase": phase},
                    success_metadata_fn=lambda result: {
                        "stage": result.get("stage"),
                        "success": bool(result.get("success")),
                    },
                )
                self._emit(
                    "auth.completed",
                    {
                        "run_id": run_id,
                        "stage": auth_result.get("stage"),
                        "success": bool(auth_result.get("success")),
                    },
                )

            phase = "exploration"
            self.run_service.update_status(
                run_id,
                "ExplorationInProgress",
                {"phase": phase, "auth_stage": auth_result.get("stage")},
            )
            exploration_result = self.temporal.run_activity(
                run_id,
                "exploration",
                lambda: self.exploration_engine.explore(run_id, resolved_site_map),
                attempt_metadata={"phase": phase},
                success_metadata_fn=lambda result: {
                    "coverage_percent": result.coverage_percent,
                    "visited_count": len(result.visited_pages),
                },
            )
            self._emit(
                "exploration.completed",
                {
                    "run_id": run_id,
                    "coverage_percent": exploration_result.coverage_percent,
                    "visited_count": len(exploration_result.visited_pages),
                    "skipped_count": len(exploration_result.skipped_pages),
                },
            )

            phase = "crawl"
            seeds = exploration_result.visited_pages
            self.run_service.update_status(
                run_id,
                "CrawlInProgress",
                {
                    "phase": phase,
                    "seed_count": len(seeds),
                    "coverage_percent": exploration_result.coverage_percent,
                },
            )
            crawl_result = self.temporal.run_activity(
                run_id,
                "crawl",
                lambda: self.crawler.crawl(run_id, seeds, resolved_adjacency),
                attempt_metadata={"phase": phase},
                success_metadata_fn=lambda result: {
                    "visited_count": len(result.visited),
                    "skipped_count": len(result.skipped),
                },
            )
            self._emit(
                "crawl.completed",
                {
                    "run_id": run_id,
                    "visited_count": len(crawl_result.visited),
                    "skipped_count": len(crawl_result.skipped),
                },
            )

            phase = "completed"
            self.run_service.update_status(
                run_id,
                "Completed",
                {
                    "phase": phase,
                    "visited": len(crawl_result.visited),
                    "skipped": len(crawl_result.skipped),
                },
            )
            self._record_checkpoint(
                run_id,
                "workflow.completed",
                {
                    "visited": len(crawl_result.visited),
                    "skipped": len(crawl_result.skipped),
                    "coverage_percent": exploration_result.coverage_percent,
                },
            )
            self._emit(
                "workflow.completed",
                {
                    "run_id": run_id,
                    "coverage_percent": exploration_result.coverage_percent,
                    "crawl_visited": len(crawl_result.visited),
                    "crawl_skipped": len(crawl_result.skipped),
                },
            )
            return {
                "run_id": run_id,
                "auth": auth_result,
                "exploration": exploration_result.to_dict(),
                "crawl": crawl_result.to_summary(),
            }
        except Exception as exc:
            failure_payload = {"phase": phase, "error": str(exc), "exception": exc.__class__.__name__}
            self._record_checkpoint(run_id, "workflow.failed", failure_payload)
            self.run_service.update_status(run_id, "Failed", failure_payload)
            self._emit(
                "workflow.failed",
                {"run_id": run_id, "phase": phase, "error": str(exc), "exception": exc.__class__.__name__},
            )
            raise

    def _execute_auth(self, run_id: str, payload: CreateRunPayload) -> Dict[str, Any]:
        credentials = payload.credentials
        if credentials.is_empty():
            raise WorkflowError("No credentials provided for authentication phase")
        result = self.auth_orchestrator.authenticate(run_id, credentials)
        if not isinstance(result, dict):
            raise WorkflowError("Authentication orchestrator returned unexpected payload")
        if not result.get("success"):
            raise WorkflowError(result.get("error", "authentication failed"))
        return result

    def _record_checkpoint(self, run_id: str, name: str, details: Dict[str, Any]) -> None:
        self.run_service.record_checkpoint(run_id, name, _safe_metadata(details))

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        try:
            self.telemetry.emit(event, _safe_metadata(payload))
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("telemetry emit failed for %s", event)

    def _bind_component_telemetry(self) -> None:
        for component in (self.exploration_engine, self.crawler):
            telemetry_attr = getattr(component, "telemetry", None)
            try:
                if telemetry_attr is None or isinstance(telemetry_attr, NoOpTelemetry):
                    setattr(component, "telemetry", self.telemetry)
            except Exception:  # pragma: no cover - defensive guard
                logger.debug("Skipping telemetry binding for %s", component.__class__.__name__)

    def _resolve_site_map(
        self,
        site_map: Iterable[PageDescriptor] | None,
        adjacency: Dict[str, List[PageDescriptor]] | None,
        payload: CreateRunPayload,
    ) -> Tuple[List[PageDescriptor], Dict[str, List[PageDescriptor]]]:
        if site_map is not None and adjacency is not None:
            return list(site_map), dict(adjacency)
        if self.site_map_builder is None:
            raise WorkflowError("Site map builder not configured and site map not provided")
        pages, graph = self.site_map_builder(payload)
        return list(pages), dict(graph)


__all__ = [
    "RunWorkflow",
    "RetryPolicy",
    "TemporalTaskRunner",
    "WorkflowError",
    "RetryableWorkflowError",
]
