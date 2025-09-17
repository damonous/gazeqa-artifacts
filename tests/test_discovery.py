from pathlib import Path

import pytest

from gazeqa.discovery import discover_site_map
from gazeqa.models import CreateRunPayload


def _payload(url: str = "https://example.test") -> CreateRunPayload:
    return CreateRunPayload.from_dict({"target_url": url})


def test_site_map_falls_back_when_playwright_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("gazeqa.discovery._sync_playwright", None, raising=False)

    pages, adjacency = discover_site_map("RUN-DISCOVERY", _payload(), tmp_path)

    assert pages, "Expected default site map"
    assert adjacency, "Expected adjacency mapping"


def test_site_map_handles_non_http_targets(tmp_path: Path) -> None:
    pages, _ = discover_site_map("RUN-NONHTTP", _payload("ftp://example"), tmp_path)
    assert pages[0].url.startswith("https://"), "Default sitemap should be used"
