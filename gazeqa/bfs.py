"""Deterministic BFS crawler scaffold for FR-004."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .exploration import PageDescriptor


@dataclass(slots=True)
class CrawlConfig:
    storage_root: Path = Path("artifacts/runs")
    max_depth: int = 3
    skip_keywords: Sequence[str] = ("logout", "signout", "sign-out")


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

    def __init__(self, config: CrawlConfig | None = None) -> None:
        self.config = config or CrawlConfig()

    def crawl(
        self,
        run_id: str,
        seeds: Iterable[PageDescriptor],
        adjacency: Dict[str, List[PageDescriptor]],
    ) -> CrawlResult:
        timestamp = datetime.now(timezone.utc).isoformat()
        visited: Dict[str, CrawlRecord] = {}
        skipped: List[SkipRecord] = []

        queue: deque[Tuple[PageDescriptor, int, Optional[PageDescriptor]]] = deque(
            (seed, 0, None) for seed in seeds
        )

        while queue:
            page, depth, parent = queue.popleft()
            key = page.url.lower()
            if key in visited:
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
        self._persist(run_id, result)
        return result

    def _should_skip(self, page: PageDescriptor) -> bool:
        if not page.url:
            return False
        lower = page.url.lower()
        return any(keyword in lower for keyword in self.config.skip_keywords)

    def _persist(self, run_id: str, result: CrawlResult) -> None:
        run_dir = self.config.storage_root / run_id / "bfs"
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


__all__ = ["BFSCrawler", "CrawlConfig", "CrawlResult", "CrawlRecord", "SkipRecord"]
