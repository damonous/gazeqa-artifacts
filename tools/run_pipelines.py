#!/usr/bin/env python3
"""Simulate selector and test generation pipelines for GazeQA artifacts."""
from __future__ import annotations

import argparse
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
import xml.etree.ElementTree as ET

ISO_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime(ISO_TIMESTAMP)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    write_text(path, text + "\n")


def build_pages_payload(run_id: str) -> List[Dict[str, object]]:
    generated_at = iso_now()
    return [
        {
            "page_id": "home",
            "run_id": run_id,
            "url": "https://demo.gazeqa.test/home",
            "title": "Demo App – Home",
            "hash": "home-3d1f0",
            "screenshot": "selectors/home_screenshot.txt",
            "dom_snapshot": "selectors/home_dom_snapshot.txt",
            "selectors_file": "selectors/home_selectors.json",
            "generated_at": generated_at,
        },
        {
            "page_id": "dashboard",
            "run_id": run_id,
            "url": "https://demo.gazeqa.test/dashboard",
            "title": "Demo App – Dashboard",
            "hash": "dashboard-7ab9c",
            "screenshot": "selectors/dashboard_screenshot.txt",
            "dom_snapshot": "selectors/dashboard_dom_snapshot.txt",
            "selectors_file": "selectors/dashboard_selectors.json",
            "generated_at": generated_at,
        },
    ]


def write_selector_artifacts(run_dir: Path, run_id: str) -> Dict[str, List[str]]:
    pages = build_pages_payload(run_id)
    selectors_dir = run_dir / "selectors"
    evidence_map: Dict[str, List[str]] = {
        "TC-FR-005-001": ["selectors/index.json", "selectors/home_selectors.json"],
        "TC-FR-005-002": ["selectors/dashboard_selectors.json", "selectors/dashboard_observations.txt"],
    }

    lines = [json.dumps(page, ensure_ascii=True) for page in pages]
    write_text(selectors_dir / "pages.jsonl", "\n".join(lines) + "\n")

    index_payload = {
        "run_id": run_id,
        "generated_at": iso_now(),
        "pages": [
            {
                "page_id": page["page_id"],
                "url": page["url"],
                "selectors_file": page["selectors_file"],
                "screenshot": page["screenshot"],
                "dom_snapshot": page["dom_snapshot"],
            }
            for page in pages
        ],
    }
    write_json(selectors_dir / "index.json", index_payload)

    home_selectors = {
        "primary_submit": {
            "css": "button[data-testid=\"primary-action\"]",
            "confidence": 0.94,
            "strategies": ["data-testid", "aria-label"],
        },
        "nav_profile": {
            "css": "nav .profile",
            "confidence": 0.88,
            "strategies": ["role=link", "text=Profile"],
        },
    }
    dashboard_selectors = {
        "graph_canvas": {
            "css": "#usage-chart canvas",
            "confidence": 0.76,
            "strategies": ["vision-model", "fallback-css"],
        },
        "export_button": {
            "css": "button[data-test=\"export-report\"]",
            "confidence": 0.91,
            "strategies": ["data-test", "text=Export"],
        },
    }
    write_json(selectors_dir / "home_selectors.json", home_selectors)
    write_json(selectors_dir / "dashboard_selectors.json", dashboard_selectors)

    write_text(selectors_dir / "home_dom_snapshot.txt", "<html>...</html>\n")
    write_text(selectors_dir / "dashboard_dom_snapshot.txt", "<html>...</html>\n")
    write_text(selectors_dir / "home_screenshot.txt", "Screenshot placeholder for home page.\n")
    write_text(selectors_dir / "dashboard_screenshot.txt", "Screenshot placeholder for dashboard page.\n")

    observations = (
        "Dashboard vision locator derived from chart title overlay; "
        "selector validated via simulated hover.\n"
    )
    write_text(selectors_dir / "dashboard_observations.txt", observations)

    return evidence_map



def build_python_tests(run_dir: Path) -> None:
    python_dir = run_dir / "tests" / "python"
    content = textwrap.dedent("""
    '''Generated PyTest stubs aligned with RTM test cases.'''
    import json
    from pathlib import Path

    SELECTORS_ROOT = Path(__file__).resolve().parents[2] / "selectors"


    def load_selector_candidates(name: str) -> dict:
        path = SELECTORS_ROOT / f"{name}_selectors.json"
        return json.loads(path.read_text())


    def test_selector_candidates_exist():
        # TC-FR-005-001: Selector candidates are persisted per page.
        candidates = load_selector_candidates("home")
        assert "primary_submit" in candidates


    def test_vision_locator_generated():
        # TC-FR-005-002: Vision analysis surfaces actionable locator.
        candidates = load_selector_candidates("dashboard")
        assert candidates["graph_canvas"]["strategies"][0] == "vision-model"


    def test_story_to_test_generation_manifest():
        # TC-FR-007-001: Generated manifest links stories to runnable tests.
        manifest = Path(__file__).resolve().parents[1] / "manifest.json"
        data = json.loads(manifest.read_text())
        assert data.get("stories")
    """)
    write_text(python_dir / "test_generated_suite.py", content)


def build_java_tests(run_dir: Path) -> None:
    java_dir = run_dir / "tests" / "java" / "src" / "test" / "java" / "com" / "gazeqa" / "generated"
    content = """package com.gazeqa.generated;

// Generated Selenium stub aligning with RTM catalog
public class GeneratedSelectorsTest {
    // TC-FR-005-001
    public void testSelectorsPersisted() {
        // Implementation placeholder – ensures selectors manifest present.
    }

    // TC-FR-007-001
    public void testScenarioManifest() {
        // Implementation placeholder – ensures scenario manifest present.
    }
}
"""
    write_text(java_dir / "GeneratedSelectorsTest.java", content)


def write_tests_manifest(run_dir: Path) -> None:
    manifest = {
        "generated_at": iso_now(),
        "stories": [
            {
                "story_id": "STORY-FR-005-LOGIN",
                "tests": [
                    {
                        "id": "TC-FR-005-001",
                        "framework": "PYTEST_PLAYWRIGHT",
                        "path": "tests/python/test_generated_suite.py::test_selector_candidates_exist",
                    }
                ],
            },
            {
                "story_id": "STORY-FR-005-VISION",
                "tests": [
                    {
                        "id": "TC-FR-005-002",
                        "framework": "PYTEST_PLAYWRIGHT",
                        "path": "tests/python/test_generated_suite.py::test_vision_locator_generated",
                    }
                ],
            },
            {
                "story_id": "STORY-FR-007-GENERATION",
                "tests": [
                    {
                        "id": "TC-FR-007-001",
                        "framework": "PYTEST_PLAYWRIGHT",
                        "path": "tests/python/test_generated_suite.py::test_story_to_test_generation_manifest",
                    }
                ],
            },
        ],
    }
    write_json(run_dir / "tests" / "manifest.json", manifest)


def write_junit_report(path: Path, testcases: Sequence[Dict[str, object]]) -> None:
    suite = ET.Element("testsuite", attrib={
        "name": "GazeQAGenerated",
        "timestamp": iso_now(),
        "tests": str(len(testcases)),
        "failures": str(sum(1 for case in testcases if case.get("status") == "failed")),
        "skipped": str(sum(1 for case in testcases if case.get("status") == "skipped")),
        "errors": "0",
    })

    for case in testcases:
        attrs = {
            "name": str(case["id"]),
            "classname": "com.gazeqa.generated.GeneratedSelectorsTest",
            "time": f"{case.get('time', 0.1):.3f}",
        }
        testcase = ET.SubElement(suite, "testcase", attrib=attrs)
        status = case.get("status", "passed")
        if status == "failed":
            failure = ET.SubElement(testcase, "failure", attrib={"message": case.get("message", "Assertion failed")})
            failure.text = case.get("details", "Generated pipeline detected drift.")
        elif status == "skipped":
            ET.SubElement(testcase, "skipped")
        evidence: Iterable[str] = case.get("evidence", [])  # type: ignore[assignment]
        if evidence:
            system_out = ET.SubElement(testcase, "system-out")
            system_out.text = "\n".join(f"EVIDENCE: {item}" for item in evidence)

    tree = ET.ElementTree(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_criteria_payload(run_dir: Path) -> None:
    criteria = {
        "criteria": [
            {
                "id": "FR-005-AC-1",
                "passed": True,
                "checked_at": iso_now(),
                "evidence": ["selectors/index.json", "selectors/pages.jsonl"],
            },
            {
                "id": "FR-005-AC-2",
                "passed": True,
                "checked_at": iso_now(),
                "evidence": ["selectors/dashboard_observations.txt"],
            },
            {
                "id": "FR-007-AC-1",
                "passed": True,
                "checked_at": iso_now(),
                "evidence": ["tests/manifest.json", "reports/junit_generated.xml"],
            },
        ]
    }
    write_json(run_dir / "reports" / "criteria.json", criteria)


def write_run_manifest(run_dir: Path, run_id: str, junit_path: Path) -> None:
    manifest = {
        "run_id": run_id,
        "generated_at": iso_now(),
        "artifacts": {
            "selectors": "selectors/index.json",
            "tests_manifest": "tests/manifest.json",
            "junit_report": junit_path.relative_to(run_dir).as_posix(),
            "criteria": "reports/criteria.json",
        },
    }
    write_json(run_dir / "run_manifest.json", manifest)


def generate_artifacts(run_dir: Path, run_id: str) -> None:
    selector_evidence = write_selector_artifacts(run_dir, run_id)
    build_python_tests(run_dir)
    build_java_tests(run_dir)
    write_tests_manifest(run_dir)

    testcases = [
        {
            "id": "TC-FR-005-001",
            "status": "passed",
            "time": 0.42,
            "evidence": selector_evidence["TC-FR-005-001"],
        },
        {
            "id": "TC-FR-005-002",
            "status": "passed",
            "time": 0.37,
            "evidence": selector_evidence["TC-FR-005-002"],
        },
        {
            "id": "TC-FR-007-001",
            "status": "passed",
            "time": 0.78,
            "evidence": ["tests/manifest.json", "tests/python/test_generated_suite.py"],
        },
    ]
    junit_path = run_dir / "reports" / "junit_generated.xml"
    write_junit_report(junit_path, testcases)

    test_evidence_map = {case["id"]: case.get("evidence", []) for case in testcases}
    write_json(run_dir / "reports" / "test_evidence.json", test_evidence_map)

    write_criteria_payload(run_dir)
    write_run_manifest(run_dir, run_id, junit_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate selector/test artifacts for a sample run.")
    parser.add_argument("--run-id", help="Run identifier; defaults to RUN-<timestamp> if omitted.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts") / "runs",
        help="Directory under which run artifacts are produced (default: artifacts/runs).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("RUN-%Y%m%d-%H%M%S")
    run_dir = args.output_root / run_id
    generate_artifacts(run_dir, run_id)
    print(f"Artifacts for {run_id} generated under {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
