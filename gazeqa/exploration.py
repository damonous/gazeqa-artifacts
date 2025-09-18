"""Exploration scaffold for FR-003 with FR-016 guardrails."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .telemetry import NoOpTelemetry, TelemetrySink
from .path_utils import resolve_run_path


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PageDescriptor:
    url: str
    title: str
    section: str
    page_id: str | None = None
    screenshot: str | None = None
    dom_snapshot: str | None = None

    def to_artifact(self) -> Dict[str, str | None]:
        return {
            "url": self.url,
            "title": self.title,
            "section": self.section,
            "page_id": self.page_id,
            "screenshot": self.screenshot,
            "dom_snapshot": self.dom_snapshot,
        }


@dataclass(slots=True)
class ExplorationConfig:
    coverage_threshold: float = 0.8
    storage_root: Path = Path("artifacts/runs")
    max_pages_per_run: int = 0
    destructive_keywords: Sequence[str] = (
        "delete",
        "destroy",
        "remove",
        "drop",
        "shutdown",
        "wipe",
    )
    guardrail_log_name: str = "guardrails.jsonl"


@dataclass(slots=True)
class ExplorationResult:
    run_id: str
    coverage_percent: float
    visited_pages: List[PageDescriptor]
    skipped_pages: List[PageDescriptor]
    timestamp: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "coverage_percent": self.coverage_percent,
            "visited_pages": [page.to_artifact() for page in self.visited_pages],
            "skipped_pages": [page.to_artifact() for page in self.skipped_pages],
            "timestamp": self.timestamp,
        }


class ExplorationEngine:
    """Simulated exploration for documentation/tests."""

    def __init__(
        self,
        config: ExplorationConfig | None = None,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.config = config or ExplorationConfig()
        self.telemetry = telemetry or NoOpTelemetry()

    def explore(self, run_id: str, site_map: Iterable[PageDescriptor]) -> ExplorationResult:
        pages = list(site_map)
        if not pages:
            raise ValueError("site_map must contain at least one page")
        budget = max(1, int(len(pages) * self.config.coverage_threshold))
        candidate_pages = pages[:budget]
        baseline_skipped = pages[budget:]

        visited: List[PageDescriptor] = []
        skipped: List[PageDescriptor] = []
        guardrail_events: List[Dict[str, object]] = []
        rate_limited = False

        for idx, page in enumerate(candidate_pages):
            keyword = self._match_keyword(page)
            if keyword:
                guardrail_events.append(
                    self._guardrail_event(run_id, "blocklist", page, keyword=keyword)
                )
                skipped.append(page)
                self._emit(
                    "guardrail.blocklist",
                    {
                        "run_id": run_id,
                        "phase": "exploration",
                        "url": page.url,
                        "keyword": keyword,
                    },
                )
                continue
            if self._rate_limited(len(visited)):
                guardrail_events.append(self._guardrail_event(run_id, "rate_limit", page))
                skipped.append(page)
                skipped.extend(candidate_pages[idx + 1 :])
                rate_limited = True
                self._emit(
                    "guardrail.rate_limit",
                    {
                        "run_id": run_id,
                        "phase": "exploration",
                        "url": page.url,
                        "limit": self.config.max_pages_per_run,
                    },
                )
                break
            visited.append(page)

        if not rate_limited:
            skipped.extend(page for page in candidate_pages if page not in visited and page not in skipped)
        skipped.extend(baseline_skipped)

        coverage = len(visited) / len(pages)
        timestamp = datetime.now(timezone.utc).isoformat()
        result = ExplorationResult(
            run_id=run_id,
            coverage_percent=round(coverage, 4),
            visited_pages=visited,
            skipped_pages=skipped,
            timestamp=timestamp,
        )
        self._persist(run_id, result, guardrail_events)
        return result

    def _persist(
        self,
        run_id: str,
        result: ExplorationResult,
        guardrail_events: List[Dict[str, object]],
    ) -> None:
        run_dir = resolve_run_path(self.config.storage_root, run_id) / "exploration"
        run_dir.mkdir(parents=True, exist_ok=True)
        coverage_path = run_dir / "coverage_report.json"
        coverage_path.write_text(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "coverage_percent": result.coverage_percent,
                    "visited_count": len(result.visited_pages),
                    "total_pages": len(result.visited_pages) + len(result.skipped_pages),
                    "generated_at": result.timestamp,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pages_path = run_dir / "visited_pages.jsonl"
        pages_path.write_text(
            "".join(
                json.dumps(page.to_artifact()) + "\n" for page in result.visited_pages
            ),
            encoding="utf-8",
        )
        skipped_path = run_dir / "skipped_pages.jsonl"
        skipped_path.write_text(
            "".join(
                json.dumps(page.to_artifact()) + "\n" for page in result.skipped_pages
            ),
            encoding="utf-8",
        )
        if guardrail_events:
            guardrail_path = run_dir / self.config.guardrail_log_name
            guardrail_path.write_text(
                "".join(json.dumps(event) + "\n" for event in guardrail_events),
                encoding="utf-8",
            )

    def _match_keyword(self, page: PageDescriptor) -> str | None:
        keywords = [kw.lower() for kw in self.config.destructive_keywords]
        haystack = f"{page.url} {page.title}".lower()
        for keyword in keywords:
            if keyword and keyword in haystack:
                return keyword
        return None

    def _rate_limited(self, processed_count: int) -> bool:
        limit = self.config.max_pages_per_run
        if limit <= 0:
            return False
        return processed_count >= limit

    def _guardrail_event(
        self,
        run_id: str,
        event_type: str,
        page: PageDescriptor,
        *,
        keyword: str | None = None,
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "run_id": run_id,
            "phase": "exploration",
            "type": event_type,
            "url": page.url,
            "title": page.title,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if keyword:
            payload["keyword"] = keyword
        if event_type == "rate_limit":
            payload["limit"] = self.config.max_pages_per_run
        return payload

    def _emit(self, event: str, payload: Dict[str, object]) -> None:
        try:
            self.telemetry.emit(event, payload)
        except Exception:  # pragma: no cover - defensive log
            logger.exception("exploration telemetry emit failed: %s", event)


__all__ = [
    "ExplorationEngine",
    "ExplorationConfig",
    "ExplorationResult",
    "PageDescriptor",
]
