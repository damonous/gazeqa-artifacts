"""Deterministic BFS crawl scaffold (FR-004)."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Set, Dict


@dataclass(slots=True)
class CrawlConfig:
    storage_root: Path = Path("artifacts/runs")
    max_depth: int = 3
    exclude_patterns: Iterable[str] | None = None


@dataclass(slots=True)
class CrawlResult:
    run_id: str
    discovered_pages: Dict[str, Dict[str, object]]
    skipped_urls: Iterable[str]
    timestamp: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "pages": self.discovered_pages,
            "skipped_urls": list(self.skipped_urls),
        }


class BFSCrawler:
    """Minimal BFS crawler over an in-memory link graph."""

    def __init__(self, config: CrawlConfig | None = None) -> None:
        self.config = config or CrawlConfig()

    def crawl(self, run_id: str, start_url: str, link_graph: Dict[str, Iterable[str]]) -> CrawlResult:
        visited: Dict[str, Dict[str, object]] = {}
        skipped: Set[str] = set()
        queue = deque([(start_url, 0)])
        exclude = list(self.config.exclude_patterns or [])

        while queue:
            current, depth = queue.popleft()
            if current in visited or current in skipped:
                continue
            if any(pattern in current for pattern in exclude):
                skipped.add(current)
                continue
            visited[current] = {"depth": depth}
            if depth >= self.config.max_depth:
                continue
            for neighbor in link_graph.get(current, []):
                queue.append((neighbor, depth + 1))

        result = CrawlResult(
            run_id=run_id,
            discovered_pages=visited,
            skipped_urls=sorted(skipped),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._persist(run_id, result)
        return result

    def _persist(self, run_id: str, result: CrawlResult) -> None:
        crawl_dir = self.config.storage_root / run_id / "crawl"
        crawl_dir.mkdir(parents=True, exist_ok=True)
        (crawl_dir / "crawl_result.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )


__all__ = ["BFSCrawler", "CrawlConfig", "CrawlResult"]
