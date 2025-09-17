"""Extended PyTest validations for FR-006/FR-007 coverage."""
import json
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[2]
FRD_EXPORT = RUN_ROOT / "frd" / "stories_export.json"
SELECTOR_ROOT = RUN_ROOT / "selectors"
SOURCE_ROOT = RUN_ROOT / "source"


def load_features():
    return json.loads(FRD_EXPORT.read_text())['features']


def test_story_catalog_includes_new_clusters():
    """TC-FR-006-001: Newly captured flows appear in synthesized stories."""
    stories = {item['story_id'] for item in load_features()}
    assert {'STORY-FR-006-REPORTS', 'STORY-FR-006-SETTINGS', 'STORY-FR-006-USERS'} <= stories


def test_reports_story_references_selectors():
    """TC-FR-006-001: Reports feature links to selector evidence."""
    reports = next(item for item in load_features() if item['story_id'] == 'STORY-FR-006-REPORTS')
    evidence = [ev for criterion in reports['acceptance_criteria'] for ev in criterion['evidence']]
    target = SELECTOR_ROOT / 'reports_selectors.json'
    assert str(target.relative_to(RUN_ROOT)) in evidence
    selectors = json.loads(target.read_text())
    assert 'reports_header' in selectors['selectors']


def test_users_story_validates_role_column():
    """TC-FR-007-001: Users story provides data for downstream tests."""
    users = next(item for item in load_features() if item['story_id'] == 'STORY-FR-006-USERS')
    target = SOURCE_ROOT / 'dom' / 'users.html'
    assert target.read_text().count('Role') >= 1
    assert any('Role' in ev for criterion in users['acceptance_criteria'] for ev in criterion['evidence'])


def test_selector_inventory_is_complete():
    """TC-FR-007-001: Selector index contains mapping for each new page cluster."""
    index = json.loads((SELECTOR_ROOT / 'index.json').read_text())
    pages = {entry['page_id'] for entry in index['selector_packages']}
    assert pages == {'reports', 'settings', 'users'}

