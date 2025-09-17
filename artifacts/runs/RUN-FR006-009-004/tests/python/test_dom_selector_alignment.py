"""Validate DOM-backed selectors for About/Team/Admin flows."""
import json
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[2]
FRD_EXPORT = RUN_ROOT / "frd" / "stories_export.json"
DOM_DIR = RUN_ROOT / "source" / "dom"
SELECTOR_DIR = RUN_ROOT / "selectors"


def load_story_ids():
    data = json.loads(FRD_EXPORT.read_text())
    return {feature['story_id'] for feature in data['features']}


def test_story_ids_cover_about_team_admin():
    """TC-FR-006-001: Ensure new stories are present for adjacency pages."""
    story_ids = load_story_ids()
    assert {'STORY-FR-006-ABOUT', 'STORY-FR-006-TEAM', 'STORY-FR-006-ADMIN'} <= story_ids


def test_about_mission_section_present():
    """TC-FR-007-001: Mission section exists for selector binding."""
    html = DOM_DIR.joinpath('about.html').read_text()
    assert 'section id="mission"' in html
    assert '<h2>Our Mission</h2>' in html


def test_team_list_has_members():
    """TC-FR-007-001: Team roster contains at least one member."""
    html = DOM_DIR.joinpath('team.html').read_text()
    assert '<ul class="team">' in html
    assert '<li>' in html and 'Engineer' in html


def test_admin_audit_table_headers():
    """TC-FR-007-001: Audit table exposes User column for downstream tests."""
    html = DOM_DIR.joinpath('admin.html').read_text()
    assert 'table class="audit"' in html
    assert '<th>User</th>' in html


def test_selector_files_align_with_dom():
    """TC-FR-007-001: Selector packages reference expected keys."""
    for name, key in [('about', 'mission_section'), ('team', 'team_list'), ('admin', 'audit_table')]:
        payload = json.loads((SELECTOR_DIR / f'{name}_selectors.json').read_text())
        assert key in payload['selectors']

