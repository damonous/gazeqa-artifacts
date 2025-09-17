import json
from pathlib import Path

from gazeqa.bfs import BFSCrawler, CrawlConfig
from gazeqa.exploration import PageDescriptor


def _page(page_id: str, url: str, title: str, section: str = "") -> PageDescriptor:
    return PageDescriptor(url=url, title=title, section=section, page_id=page_id)


def test_bfs_crawl_persists_artifacts(tmp_path: Path) -> None:
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path, max_depth=2))
    home = _page("home", "https://example.test/home", "Home")
    dashboard = _page("dashboard", "https://example.test/dashboard", "Dashboard")
    settings = _page("settings", "https://example.test/settings", "Settings")
    logout = _page("logout", "https://example.test/logout", "Logout")

    adjacency = {
        "home": [dashboard, logout],
        "dashboard": [settings],
    }

    result = crawler.crawl("RUN-BFS-TEST", [home], adjacency)

    run_dir = tmp_path / "RUN-BFS-TEST" / "bfs"
    page_map = (run_dir / "page_map.jsonl").read_text().strip().splitlines()
    assert len(page_map) == 3  # home, dashboard, settings

    skipped = json.loads((run_dir / "skipped_links.json").read_text())
    assert skipped[0]["url"].endswith("/logout")

    summary = json.loads((run_dir / "coverage_merge.json").read_text())
    assert summary["visited_count"] == 3
    assert Path(page_map[0])  # ensure entries were written

    # Result metadata
    assert result.visited[0].page.page_id == "home"
    assert result.skipped[0].source_page_id == "home"


def test_bfs_guardrail_rate_limit(tmp_path: Path) -> None:
    crawler = BFSCrawler(
        CrawlConfig(storage_root=tmp_path, max_depth=3, max_nodes_per_run=1)
    )
    home = _page("home", "https://example.test/home", "Home")
    about = _page("about", "https://example.test/about", "About")
    contact = _page("contact", "https://example.test/contact", "Contact")

    adjacency = {"home": [about, contact]}
    result = crawler.crawl("RUN-BFS-GR", [home], adjacency)

    assert len(result.visited) == 1
    guardrail_path = tmp_path / "RUN-BFS-GR" / "bfs" / "guardrails.jsonl"
    entries = [json.loads(line) for line in guardrail_path.read_text().splitlines() if line.strip()]
    assert entries[0]["type"] == "rate_limit"


def test_bfs_guardrail_blocklist(tmp_path: Path) -> None:
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path, max_depth=1))
    home = _page("home", "https://example.test/home", "Home")
    delete_page = _page("delete", "https://example.test/admin/delete", "Delete")

    adjacency = {"home": [delete_page]}
    result = crawler.crawl("RUN-BFS-BLOCK", [home], adjacency)

    guardrail_path = tmp_path / "RUN-BFS-BLOCK" / "bfs" / "guardrails.jsonl"
    entries = [json.loads(line) for line in guardrail_path.read_text().splitlines() if line.strip()]
    assert any(entry["type"] == "blocklist" for entry in entries)
    assert any(record.reason == "destructive_blocklist" for record in result.skipped)
