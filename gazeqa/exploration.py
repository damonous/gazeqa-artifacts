"""Exploration scaffold for FR-003."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Dict


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

    def __init__(self, config: ExplorationConfig | None = None) -> None:
        self.config = config or ExplorationConfig()

    def explore(self, run_id: str, site_map: Iterable[PageDescriptor]) -> ExplorationResult:
        pages = list(site_map)
        if not pages:
            raise ValueError("site_map must contain at least one page")
        budget = max(1, int(len(pages) * self.config.coverage_threshold))
        visited = pages[:budget]
        skipped = pages[budget:]
        coverage = len(visited) / len(pages)
        timestamp = datetime.now(timezone.utc).isoformat()
        result = ExplorationResult(
            run_id=run_id,
            coverage_percent=round(coverage, 4),
            visited_pages=visited,
            skipped_pages=skipped,
            timestamp=timestamp,
        )
        self._persist(run_id, result)
        return result

    def _persist(self, run_id: str, result: ExplorationResult) -> None:
        run_dir = self.config.storage_root / run_id / "exploration"
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


__all__ = [
    "ExplorationEngine",
    "ExplorationConfig",
    "ExplorationResult",
    "PageDescriptor",
]
