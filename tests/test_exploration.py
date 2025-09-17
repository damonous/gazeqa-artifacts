import json
import shutil
import tempfile
from pathlib import Path

from gazeqa.exploration import ExplorationEngine, ExplorationConfig, PageDescriptor


def _sample_site() -> list[PageDescriptor]:
    return [
        PageDescriptor(url=f"https://example.test/page{i}", title=f"Page {i}", section="section" if i < 3 else "detail")
        for i in range(1, 6)
    ]


def test_exploration_persists_artifacts(tmp_path: Path) -> None:
    engine = ExplorationEngine(ExplorationConfig(coverage_threshold=0.6, storage_root=tmp_path))
    result = engine.explore("RUN-EXP-001", _sample_site())

    assert result.coverage_percent >= 0.6
    run_dir = tmp_path / "RUN-EXP-001" / "exploration"
    coverage_report = json.loads((run_dir / "coverage_report.json").read_text())
    assert coverage_report["visited_count"] == len(result.visited_pages)
    visited_lines = (run_dir / "visited_pages.jsonl").read_text().strip().splitlines()
    assert len(visited_lines) == len(result.visited_pages)


def test_exploration_requires_pages() -> None:
    engine = ExplorationEngine()
    with tempfile.TemporaryDirectory() as tmp:
        engine.config.storage_root = Path(tmp)
        try:
            engine.explore("RUN", [])
        except ValueError as exc:
            assert "site_map" in str(exc)
        else:  # pragma: no cover
            assert False
