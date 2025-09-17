"""Generated PyTest suite for synthesized requirements and selector alignment."""
import json
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[2]
FRD_EXPORT = RUN_ROOT / "frd" / "stories_export.json"
SELECTORS_ROOT = RUN_ROOT / "selectors"
JAVA_SUITE_ROOT = RUN_ROOT / "tests" / "java"


def load_stories() -> dict:
    return json.loads(FRD_EXPORT.read_text())


def test_story_catalog_includes_three_features():
    """TC-FR-007-001: Every synthesized feature maps to an executable scenario."""
    stories = load_stories()["features"]
    assert len(stories) == 3
    ids = {item["story_id"] for item in stories}
    assert ids == {
        "STORY-FR-006-DASHBOARD",
        "STORY-FR-006-LOGIN",
        "STORY-FR-006-SCENARIO-AUTHORING",
    }


def test_acceptance_criteria_embed_evidence_paths():
    """TC-FR-006-001: Story export preserves evidence links for review."""
    for feature in load_stories()["features"]:
        for criterion in feature["acceptance_criteria"]:
            assert criterion["evidence"], f"Missing evidence for {criterion['id']}"


def test_imported_selectors_available_for_dashboard():
    """TC-FR-005-001 (dependency check): Selector packages remain accessible for downstream tests."""
    selector_file = SELECTORS_ROOT / "dashboard_selectors.json"
    dashboard_selectors = json.loads(selector_file.read_text())
    assert "graph_canvas" in dashboard_selectors


def test_java_suite_declares_story_mappings():
    """TC-FR-007-001: Java suite references synthesized story ids in annotations."""
    suite_file = JAVA_SUITE_ROOT / "src" / "test" / "java" / "com" / "gazeqa" / "generated" / "StoryLifecycleTest.java"
    text = suite_file.read_text()
    assert "STORY-FR-006-DASHBOARD" in text
    assert "STORY-FR-006-LOGIN" in text
    assert "STORY-FR-006-SCENARIO-AUTHORING" in text


