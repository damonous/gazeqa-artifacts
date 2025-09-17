#!/usr/bin/env python3
"""Update docs/gaze_qa_checklist_v_4.json based on a run summary file."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

DEFAULT_CHECKLIST_PATH = Path("docs/gaze_qa_checklist_v_4.json")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    path.write_text(text + "\n", encoding="utf-8")


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_evidence(items: List[str], evidence_root: Optional[Path]) -> List[str]:
    if evidence_root is None:
        return list(items)
    result: List[str] = []
    for item in items:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = evidence_root / candidate
        result.append(str(candidate))
    return result


def update_metadata(checklist: Dict[str, Any], run_summary: Dict[str, Any]) -> None:
    meta = checklist.get("metadata", {}).get("run", {})
    if "env" in run_summary:
        meta["env"] = run_summary["env"]
    if "build_sha" in run_summary:
        meta["build_sha"] = run_summary["build_sha"]
    if "run_id" in run_summary:
        meta["test_run_id"] = run_summary["run_id"]
    if run_summary.get("started_at"):
        meta["started_at"] = run_summary["started_at"]
    if run_summary.get("finished_at"):
        meta["finished_at"] = run_summary["finished_at"]
    checklist.setdefault("metadata", {})["run"] = meta


def recalc_summary(checklist: Dict[str, Any]) -> None:
    entries = checklist.get("entries", [])
    requirements_total = len(entries)
    requirements_verified = 0
    criteria_total = 0
    criteria_passed = 0
    for entry in entries:
        criteria = entry.get("criteria", [])
        criteria_total += len(criteria)
        criteria_passed += sum(1 for c in criteria if c.get("passed"))
        if entry.get("verification", {}).get("verification_passed"):
            requirements_verified += 1
    checklist.setdefault("summary", {})
    checklist["summary"].update({
        "requirements_total": requirements_total,
        "requirements_verified": requirements_verified,
        "criteria_total": criteria_total,
        "criteria_passed": criteria_passed,
    })


def merge_test_results(entry: Dict[str, Any], tests_by_id: Dict[str, Dict[str, Any]], now: str) -> bool:
    expected_tests: List[str] = entry.get("tests", [])
    if not expected_tests:
        return False
    verification = entry.setdefault("verification", {})
    observed = []
    evidence: List[str] = []
    for test_id in expected_tests:
        test_result = tests_by_id.get(test_id)
        if test_result is None:
            continue
        status = test_result.get("status", "").lower()
        observed.append(status == "passed")
        evidence.extend(test_result.get("evidence", []))
    if not observed:
        return False
    verification["test_coverage"] = all(observed)
    if evidence:
        existing_bundle = verification.get("evidence_bundle", [])
        merged = list(dict.fromkeys(existing_bundle + evidence))
        verification["evidence_bundle"] = merged
    verification.setdefault("last_verified", now)
    return True


def merge_criteria(entry: Dict[str, Any], criteria_by_id: Dict[str, Dict[str, Any]], now: str) -> bool:
    criteria = entry.get("criteria", [])
    if not criteria:
        return False
    touched = False
    for criterion in criteria:
        cid = criterion.get("id")
        result = criteria_by_id.get(cid)
        if result is None:
            continue
        touched = True
        criterion["passed"] = bool(result.get("passed"))
        evidence = result.get("evidence", [])
        if evidence:
            existing = criterion.get("evidence", [])
            criterion["evidence"] = list(dict.fromkeys(existing + evidence))
        criterion["last_checked"] = result.get("checked_at", now)
    return touched


def finalize_entry(entry: Dict[str, Any], now: str, criteria_updated: bool, tests_updated: bool) -> None:
    verification = entry.setdefault("verification", {})
    criteria = entry.get("criteria", [])
    missing_criteria = any(c.get("last_checked") is None for c in criteria) if criteria else False
    all_criteria_passed = all(c.get("passed") for c in criteria) if criteria else False
    test_coverage = verification.get("test_coverage", False)
    verification["criteria_complete"] = bool(criteria) and not missing_criteria
    previous_tests_complete = verification.get("tests_complete", False)
    if tests_updated:
        verification["tests_complete"] = bool(test_coverage and tests_updated)
    else:
        verification.setdefault("tests_complete", previous_tests_complete)
    verification_passed = bool(verification["criteria_complete"] and verification.get("tests_complete") and all_criteria_passed)
    verification["verification_passed"] = verification_passed
    if verification_passed:
        verification.setdefault("last_verified", now)
    elif criteria_updated or tests_updated:
        verification["last_verified"] = now


def apply_run_results(
    checklist: Dict[str, Any],
    run_summary: Dict[str, Any],
    evidence_root: Optional[Path],
) -> None:
    now = iso_now()
    tests = run_summary.get("tests", [])
    criteria_results = run_summary.get("criteria", [])
    tests_by_id = {
        item.get("id"): {**item, "evidence": normalize_evidence(item.get("evidence", []), evidence_root)}
        for item in tests
        if item.get("id")
    }
    criteria_by_id = {
        item.get("id"): {**item, "evidence": normalize_evidence(item.get("evidence", []), evidence_root)}
        for item in criteria_results
        if item.get("id")
    }
    for entry in checklist.get("entries", []):
        criteria_touched = merge_criteria(entry, criteria_by_id, now)
        tests_touched = merge_test_results(entry, tests_by_id, now)
        finalize_entry(entry, now, criteria_touched, tests_touched)
    update_metadata(checklist, run_summary)
    recalc_summary(checklist)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync GazeQA checklist with automated run results.")
    parser.add_argument("run_summary", type=Path, help="Path to JSON file with run summary data.")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST_PATH, help="Checklist JSON to update (default: docs/gaze_qa_checklist_v_4.json).")
    parser.add_argument("--evidence-root", type=Path, default=None, help="Optional root directory prepended to relative evidence paths.")
    args = parser.parse_args()

    checklist = load_json(args.checklist)
    run_summary = load_json(args.run_summary)
    apply_run_results(checklist, run_summary, args.evidence_root)
    dump_json(args.checklist, checklist)


if __name__ == "__main__":
    main()
