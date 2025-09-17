"""Tests for extended synthesis using adjacency map data."""
import json
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[2]
FRD_EXPORT = RUN_ROOT / "frd" / "stories_export.json"
CRAWL_RESULT = RUN_ROOT / "source" / "crawl" / "crawl_result.json"
SELECTOR_ROOT = RUN_ROOT / "selectors"


def load_features():
    return json.loads(FRD_EXPORT.read_text())['features']


def load_crawl_pages():
    data = json.loads(CRAWL_RESULT.read_text())
    return data['pages']


def test_new_story_ids_present():
    """TC-FR-006-001: Ensure new adjacency-driven stories exist."""
    story_ids = {feature['story_id'] for feature in load_features()}
    assert {'STORY-FR-006-ABOUT', 'STORY-FR-006-TEAM', 'STORY-FR-006-ADMIN'} <= story_ids


def test_crawl_contains_about_team_admin():
    """TC-FR-007-001: Crawl result enumerates target pages for scenario derivation."""
    pages = load_crawl_pages()
    assert 'https://example.test/about' in pages
    assert 'https://example.test/team' in pages
    assert 'https://example.test/admin' in pages
    assert pages['https://example.test/admin']['depth'] == 2


def test_selector_packages_exported():
    """TC-FR-007-001: Selector exports include strategies for each new page."""
    for name in ('about', 'team', 'admin'):
        payload = json.loads((SELECTOR_ROOT / f'{name}_selectors.json').read_text())
        assert payload['selectors'], f"selectors missing for {name}"

