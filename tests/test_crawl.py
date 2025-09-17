from pathlib import Path

from gazeqa.crawl import BFSCrawler, CrawlConfig


def test_bfs_crawl_persists_results(tmp_path: Path) -> None:
    graph = {
        "https://example.test/home": [
            "https://example.test/about",
            "https://example.test/settings"
        ],
        "https://example.test/about": ["https://example.test/team"],
        "https://example.test/settings": ["https://example.test/admin"],
    }
    crawler = BFSCrawler(CrawlConfig(storage_root=tmp_path, max_depth=2, exclude_patterns=["admin"]))
    result = crawler.crawl("RUN-CRAWL-001", "https://example.test/home", graph)
    assert "https://example.test/home" in result.discovered_pages
    assert "https://example.test/admin" in result.skipped_urls
    output = (tmp_path / "RUN-CRAWL-001" / "crawl" / "crawl_result.json").read_text()
    assert "RUN-CRAWL-001" in output
