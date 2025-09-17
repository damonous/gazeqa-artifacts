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


def test_exploration_rate_limit_guardrail(tmp_path: Path) -> None:
    config = ExplorationConfig(
        coverage_threshold=1.0,
        storage_root=tmp_path,
        max_pages_per_run=1,
    )
    engine = ExplorationEngine(config)
    pages = [
        PageDescriptor(url="https://example.test/safe", title="Safe", section="mission"),
        PageDescriptor(url="https://example.test/more", title="More", section="mission"),
    ]

    result = engine.explore("RUN-EXP-GR", pages)

    assert len(result.visited_pages) == 1
    guardrail_path = tmp_path / "RUN-EXP-GR" / "exploration" / "guardrails.jsonl"
    entries = [json.loads(line) for line in guardrail_path.read_text().splitlines() if line.strip()]
    assert entries[0]["type"] == "rate_limit"


def test_exploration_blocklist_guardrail(tmp_path: Path) -> None:
    config = ExplorationConfig(coverage_threshold=1.0, storage_root=tmp_path)
    engine = ExplorationEngine(config)
    pages = [
        PageDescriptor(url="https://example.test/safe", title="Safe", section="mission"),
        PageDescriptor(url="https://example.test/admin/delete", title="Delete", section="mission"),
    ]

    result = engine.explore("RUN-EXP-BLOCK", pages)
    guardrail_path = tmp_path / "RUN-EXP-BLOCK" / "exploration" / "guardrails.jsonl"
    entries = [json.loads(line) for line in guardrail_path.read_text().splitlines() if line.strip()]
    assert any(entry["type"] == "blocklist" for entry in entries)
    assert any(page.url.endswith("/admin/delete") for page in result.skipped_pages)
