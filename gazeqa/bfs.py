"""Deterministic BFS crawler scaffold for FR-004 with FR-016 guardrails."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .exploration import PageDescriptor
from .telemetry import NoOpTelemetry, TelemetrySink
from .path_utils import resolve_run_path


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CrawlConfig:
    storage_root: Path = Path("artifacts/runs")
    max_depth: int = 3
    skip_keywords: Sequence[str] = ("logout", "signout", "sign-out")
    max_nodes_per_run: int = 0
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
class CrawlRecord:
    page: PageDescriptor
    depth: int
    source_page_id: Optional[str]

    def to_artifact(self) -> Dict[str, object]:
        payload = {
            "page_id": self.page.page_id,
            "url": self.page.url,
            "title": self.page.title,
            "section": self.page.section,
            "depth": self.depth,
            "source_page_id": self.source_page_id,
            "screenshot": self.page.screenshot,
            "dom_snapshot": self.page.dom_snapshot,
        }
        return payload


@dataclass(slots=True)
class SkipRecord:
    url: str
    reason: str
    source_page_id: Optional[str]
    source_url: Optional[str]

    def to_artifact(self) -> Dict[str, object]:
        return {
            "url": self.url,
            "reason": self.reason,
            "source_page_id": self.source_page_id,
            "source_url": self.source_url,
        }


@dataclass(slots=True)
class CrawlResult:
    run_id: str
    visited: List[CrawlRecord]
    skipped: List[SkipRecord]
    timestamp: str

    def to_summary(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "visited_count": len(self.visited),
            "skipped_count": len(self.skipped),
            "generated_at": self.timestamp,
        }


class BFSCrawler:
    """Simplified BFS crawler that records visited and skipped pages."""

    def __init__(
        self,
        config: CrawlConfig | None = None,
        telemetry: TelemetrySink | None = None,
    ) -> None:
        self.config = config or CrawlConfig()
        self.telemetry = telemetry or NoOpTelemetry()

    def crawl(
        self,
        run_id: str,
        seeds: Iterable[PageDescriptor],
        adjacency: Dict[str, List[PageDescriptor]],
    ) -> CrawlResult:
        timestamp = datetime.now(timezone.utc).isoformat()
        visited: Dict[str, CrawlRecord] = {}
        skipped: List[SkipRecord] = []
        guardrail_events: List[Dict[str, object]] = []

        queue: deque[Tuple[PageDescriptor, int, Optional[PageDescriptor]]] = deque(
            (seed, 0, None) for seed in seeds
        )

        while queue:
            page, depth, parent = queue.popleft()
            key = page.url.lower()
            if key in visited:
                continue

            if self._rate_limited(len(visited)):
                guardrail_events.append(
                    self._guardrail_event(run_id, "rate_limit", page, depth, parent)
                )
                skipped.append(
                    SkipRecord(
                        url=page.url,
                        reason="rate_limited",
                        source_page_id=parent.page_id if parent else None,
                        source_url=parent.url if parent else None,
                    )
                )
                self._emit(
                    "guardrail.rate_limit",
                    {
                        "run_id": run_id,
                        "phase": "crawl",
                        "url": page.url,
                        "limit": self.config.max_nodes_per_run,
                    },
                )
                break

            keyword = self._match_keyword(page)
            if keyword:
                guardrail_events.append(
                    self._guardrail_event(run_id, "blocklist", page, depth, parent, keyword=keyword)
                )
                skipped.append(
                    SkipRecord(
                        url=page.url,
                        reason="destructive_blocklist",
                        source_page_id=parent.page_id if parent else None,
                        source_url=parent.url if parent else None,
                    )
                )
                self._emit(
                    "guardrail.blocklist",
                    {
                        "run_id": run_id,
                        "phase": "crawl",
                        "url": page.url,
                        "keyword": keyword,
                    },
                )
                continue

            if self._should_skip(page):
                skipped.append(
                    SkipRecord(
                        url=page.url,
                        reason="skip_keyword_match",
                        source_page_id=parent.page_id if parent else None,
                        source_url=parent.url if parent else None,
                    )
                )
                continue

            record = CrawlRecord(page=page, depth=depth, source_page_id=parent.page_id if parent else None)
            visited[key] = record

            if depth >= self.config.max_depth:
                continue

            children = adjacency.get(page.page_id or page.url, [])
            for child in children:
                queue.append((child, depth + 1, page))

        result = CrawlResult(
            run_id=run_id,
            visited=list(visited.values()),
            skipped=skipped,
            timestamp=timestamp,
        )
        self._persist(run_id, result, guardrail_events)
        return result

    def _should_skip(self, page: PageDescriptor) -> bool:
        if not page.url:
            return False
        lower = page.url.lower()
        return any(keyword in lower for keyword in self.config.skip_keywords)

    def _persist(
        self,
        run_id: str,
        result: CrawlResult,
        guardrail_events: List[Dict[str, object]],
    ) -> None:
        run_dir = resolve_run_path(self.config.storage_root, run_id) / "bfs"
        run_dir.mkdir(parents=True, exist_ok=True)

        page_map_path = run_dir / "page_map.jsonl"
        page_map_path.write_text(
            "".join(json.dumps(record.to_artifact()) + "\n" for record in result.visited),
            encoding="utf-8",
        )

        skipped_path = run_dir / "skipped_links.json"
        skipped_path.write_text(
            json.dumps([record.to_artifact() for record in result.skipped], indent=2),
            encoding="utf-8",
        )

        coverage_path = run_dir / "coverage_merge.json"
        coverage_path.write_text(
            json.dumps(result.to_summary(), indent=2),
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

    def _rate_limited(self, visited_count: int) -> bool:
        limit = self.config.max_nodes_per_run
        if limit <= 0:
            return False
        return visited_count >= limit

    def _guardrail_event(
        self,
        run_id: str,
        event_type: str,
        page: PageDescriptor,
        depth: int,
        parent: Optional[PageDescriptor],
        *,
        keyword: str | None = None,
    ) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "run_id": run_id,
            "phase": "crawl",
            "type": event_type,
            "url": page.url,
            "title": page.title,
            "depth": depth,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if parent:
            payload["source_page_id"] = parent.page_id
            payload["source_url"] = parent.url
        if keyword:
            payload["keyword"] = keyword
        if event_type == "rate_limit":
            payload["limit"] = self.config.max_nodes_per_run
        return payload

    def _emit(self, event: str, payload: Dict[str, object]) -> None:
        try:
            self.telemetry.emit(event, payload)
        except Exception:  # pragma: no cover - defensive log
            logger.exception("bfs telemetry emit failed: %s", event)


__all__ = ["BFSCrawler", "CrawlConfig", "CrawlResult", "CrawlRecord", "SkipRecord"]
