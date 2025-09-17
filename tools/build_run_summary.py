#!/usr/bin/env python3
"""Generate a run summary JSON for checklist auto-updates."""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

RunSummary = Dict[str, Any]


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    path.write_text(text + "\n", encoding="utf-8")


def normalize_evidence(items: Iterable[str], artifact_root: Optional[Path]) -> List[str]:
    normalized: List[str] = []
    for item in items:
        candidate = Path(item)
        if artifact_root and not candidate.is_absolute():
            candidate = artifact_root / candidate
        normalized.append(str(candidate))
    return normalized


def extract_evidence_from_testcase(testcase: ET.Element) -> List[str]:
    evidence: List[str] = []
    for prop in testcase.findall("./properties/property"):
        name = prop.get("name", "")
        value = prop.get("value")
        if not value:
            continue
        if name.lower().startswith("evidence") or name.lower() in {"artifact", "artifacts"}:
            evidence.extend(map(str.strip, value.split(";")))
    for node in testcase.findall("system-out"):
        if node.text:
            for line in node.text.strip().splitlines():
                marker = "EVIDENCE:"
                if line.strip().startswith(marker):
                    evidence.append(line.strip()[len(marker) :].strip())
    return [item for item in evidence if item]


def parse_junit_file(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:  # pragma: no cover - defensive
        print(f"Failed to parse JUnit XML {path}: {exc}", file=sys.stderr)
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    for testcase in tree.findall(".//testcase"):
        test_id = testcase.get("name")
        if not test_id:
            continue
        status = "passed"
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            status = "failed"
        elif testcase.find("skipped") is not None:
            status = "skipped"
        evidence = extract_evidence_from_testcase(testcase)
        existing = results.get(test_id)
        if existing:
            if existing["status"] == "passed" and status != "passed":
                existing["status"] = status
            existing["evidence"].extend(evidence)
        else:
            results[test_id] = {"id": test_id, "status": status, "evidence": evidence}
    return results


def merge_test_sources(
    junit_files: List[Path],
    direct_tests: List[str],
    artifact_root: Optional[Path],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for junit in junit_files:
        for test_id, data in parse_junit_file(junit).items():
            target = merged.setdefault(test_id, {"id": test_id, "status": "passed", "evidence": []})
            if target["status"] == "passed" and data["status"] != "passed":
                target["status"] = data["status"]
            target["evidence"].extend(data.get("evidence", []))
    for entry in direct_tests:
        try:
            test_id, status = entry.split("=", 1)
        except ValueError:
            print(f"Ignoring malformed --test entry '{entry}'", file=sys.stderr)
            continue
        target = merged.setdefault(test_id, {"id": test_id, "status": status.lower(), "evidence": []})
        target["status"] = status.lower()
    for data in merged.values():
        data["evidence"] = normalize_evidence(data.get("evidence", []), artifact_root)
    return sorted(merged.values(), key=lambda item: item["id"])


def load_evidence_maps(paths: List[Path]) -> Dict[str, List[str]]:
    combined: Dict[str, List[str]] = defaultdict(list)
    for path in paths:
        data = load_json(path)
        if isinstance(data, dict):
            for key, values in data.items():
                if isinstance(values, list):
                    combined[key].extend(str(v) for v in values)
    return combined


def apply_additional_evidence(
    tests: List[Dict[str, Any]],
    evidence_map: Dict[str, List[str]],
    artifact_root: Optional[Path],
) -> None:
    for test in tests:
        extra = evidence_map.get(test["id"])
        if not extra:
            continue
        normalized = normalize_evidence(extra, artifact_root)
        existing = test.setdefault("evidence", [])
        existing.extend(normalized)
        # Deduplicate while preserving order
        seen: Dict[str, None] = {}
        test["evidence"] = [seen.setdefault(item, None) or item for item in existing if item not in seen]


def load_criteria(paths: List[Path], artifact_root: Optional[Path]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for path in paths:
        data = load_json(path)
        if isinstance(data, dict):
            data = data.get("criteria", [])
        if not isinstance(data, list):
            continue
        for item in data:
            cid = item.get("id")
            if not cid:
                continue
            normalized = {
                "id": cid,
                "passed": bool(item.get("passed")),
                "checked_at": item.get("checked_at") or iso_now(),
                "evidence": normalize_evidence(item.get("evidence", []), artifact_root),
            }
            results.append(normalized)
    return results


def build_run_summary(args: argparse.Namespace) -> RunSummary:
    artifact_root = args.artifact_root
    tests = merge_test_sources(args.junit or [], args.test or [], artifact_root)
    evidence_map = load_evidence_maps(args.test_evidence or [])
    if evidence_map:
        apply_additional_evidence(tests, evidence_map, artifact_root)
    criteria = load_criteria(args.criteria_json or [], artifact_root)

    summary: RunSummary = {
        "run_id": args.run_id,
        "env": args.env,
        "build_sha": args.build_sha,
        "started_at": args.started_at or iso_now(),
        "finished_at": args.finished_at or iso_now(),
        "tests": tests,
        "criteria": criteria,
    }
    # prune None
    summary = {k: v for k, v in summary.items() if v is not None}
    return summary


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build run_summary.json for checklist updater.")
    parser.add_argument("--run-id", required=True, help="Unique identifier for the run.")
    parser.add_argument("--env", default="ci", help="Environment label (default: ci).")
    parser.add_argument("--build-sha", help="Git SHA or build identifier.")
    parser.add_argument("--started-at", help="Run start timestamp (ISO 8601).")
    parser.add_argument("--finished-at", help="Run finish timestamp (ISO 8601).")
    parser.add_argument("--artifact-root", type=Path, help="Base directory to prefix relative evidence paths.")
    parser.add_argument("--junit", type=Path, action="append", help="Path to JUnit XML file (repeatable).")
    parser.add_argument(
        "--test",
        action="append",
        help="Manually specify test result as TEST_ID=STATUS (repeatable).",
    )
    parser.add_argument(
        "--test-evidence",
        type=Path,
        action="append",
        help="JSON file mapping test ids to evidence paths (repeatable).",
    )
    parser.add_argument(
        "--criteria-json",
        type=Path,
        action="append",
        help="JSON file containing acceptance criteria results.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output path for run summary JSON.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    summary = build_run_summary(args)
    write_json(args.output, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
