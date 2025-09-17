#!/usr/bin/env python3
"""Convert run summary and checklist data into Prometheus metrics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

Metric = Tuple[str, Dict[str, str], float, str]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def to_float(value: int | float) -> float:
    return float(value)


def iter_metrics(run_data: Dict[str, Any], checklist: Dict[str, Any] | None) -> Iterable[Metric]:
    run_id = run_data.get("run_id", "unknown")
    env = run_data.get("env", "")
    labels = {"run_id": run_id}
    if env:
        labels["env"] = env

    tests: List[Dict[str, Any]] = run_data.get("tests", [])
    total_tests = len(tests)
    passed_tests = sum(1 for item in tests if item.get("status", "").lower() == "passed")
    failed_tests = sum(1 for item in tests if item.get("status", "").lower() == "failed")
    yield ("gazeqa_tests_total", labels, to_float(total_tests), "Total RTM tests reported by run summary")
    yield ("gazeqa_tests_passed", labels, to_float(passed_tests), "Passed RTM tests for run")
    yield ("gazeqa_tests_failed", labels, to_float(failed_tests), "Failed RTM tests for run")

    criteria = run_data.get("criteria", [])
    total_criteria = len(criteria)
    passed_criteria = sum(1 for item in criteria if item.get("passed"))
    yield ("gazeqa_criteria_total", labels, to_float(total_criteria), "Acceptance criteria evaluated in run summary")
    yield ("gazeqa_criteria_passed", labels, to_float(passed_criteria), "Acceptance criteria passed in run summary")

    checklist_summary = (checklist or {}).get("summary") if checklist else None
    if checklist_summary:
        base_labels = {"env": env or "unknown"}
        for key, metric_name in (
            ("requirements_total", "gazeqa_requirements_total"),
            ("requirements_verified", "gazeqa_requirements_verified"),
            ("criteria_total", "gazeqa_checklist_criteria_total"),
            ("criteria_passed", "gazeqa_checklist_criteria_passed"),
        ):
            value = checklist_summary.get(key)
            if value is not None:
                yield (metric_name, base_labels, to_float(value), f"Checklist summary field {key}")


def format_metric(name: str, labels: Dict[str, str], value: float, help_text: str, emitted_help: Dict[str, bool]) -> List[str]:
    lines: List[str] = []
    if help_text and not emitted_help.get(name):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        emitted_help[name] = True
    label_parts = [f'{key}="{value}"' for key, value in sorted(labels.items())]
    label_str = "{" + ",".join(label_parts) + "}" if label_parts else ""
    lines.append(f"{name}{label_str} {value}")
    return lines


def write_metrics(metrics: Iterable[Metric], output: Path, append: bool) -> None:
    emitted_help: Dict[str, bool] = {}
    lines: List[str] = []
    for name, labels, value, help_text in metrics:
        lines.extend(format_metric(name, labels, value, help_text, emitted_help))
    mode = "a" if append else "w"
    with output.open(mode, encoding="utf-8") as handle:
        if lines:
            handle.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Prometheus metrics for RTM runs.")
    parser.add_argument("run_summary", type=Path, help="Path to run_summary.json produced by tools/build_run_summary.py")
    parser.add_argument("--checklist", type=Path, help="Optional path to docs/gaze_qa_checklist_v_4.json for global metrics.")
    parser.add_argument("--output", type=Path, required=True, help="Output path for Prometheus text-format metrics.")
    parser.add_argument("--append", action="store_true", help="Append to existing metrics file instead of overwriting.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    run_data = load_json(args.run_summary)
    checklist = load_json(args.checklist) if args.checklist else None
    metrics = iter_metrics(run_data, checklist)
    write_metrics(metrics, args.output, append=args.append)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
