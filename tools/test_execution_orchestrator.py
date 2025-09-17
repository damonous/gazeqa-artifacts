#!/usr/bin/env python3
"""Execute generated test suites (FR-014) and produce artifacts."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

DEFAULT_OUTPUT = Path("artifacts/runs/RUN-FR014-EXEC")


Command = Tuple[List[str], Path]


def load_manifest(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_python_tests(manifest: Dict[str, object], run_root: Path) -> List[str]:
    tests: List[str] = []
    for story in manifest.get("stories", []):
        for case in story.get("tests", []):
            framework = str(case.get("framework", "")).upper()
            if framework.startswith("PYTEST"):
                path = case.get("path")
                if path:
                    tests.append(path)
    unique = sorted(set(tests))
    return [run_root / entry.split('::')[0] for entry in unique]


def collect_java_project(run_root: Path) -> Path | None:
    java_dir = run_root / "tests" / "java"
    return java_dir if java_dir.exists() else None


def run_command(command: List[str], cwd: Path, env: Dict[str, str], log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout
        for line in process.stdout:
            log_file.write(line)
        return process.wait()


def orchestrate(manifest_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_root = manifest_path.parent.parent
    manifest = load_manifest(manifest_path)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(Path.cwd()))

    python_tests = collect_python_tests(manifest, run_root)
    logs_dir = output_dir / "logs"
    reports_dir = output_dir / "reports"
    execution_dir = output_dir / "execution"
    for directory in (logs_dir, reports_dir, execution_dir):
        directory.mkdir(parents=True, exist_ok=True)

    trace: List[Dict[str, object]] = []

    if python_tests:
        junit_path = execution_dir / "junit_python.xml"
        command = [
            "pytest",
            "--junitxml",
            str(junit_path),
        ] + [str(path) for path in python_tests]
        log_path = logs_dir / "pytest.log"
        exit_code = run_command(command, Path.cwd(), env, log_path)
        trace.append({
            "command": command,
            "cwd": str(Path.cwd()),
            "exit_code": exit_code,
            "junit": str(junit_path.relative_to(output_dir)),
        })

    java_dir = collect_java_project(run_root)
    java_reports_rel = None
    if java_dir:
        junit_dir = execution_dir / "java"
        junit_dir.mkdir(exist_ok=True)
        log_path = logs_dir / "maven.log"
        mvn_env = env.copy()
        mvn_env.setdefault("JAVA_HOME", str(Path.cwd() / "tools" / "java" / "jdk-17.0.11+9"))
        mvn_env.setdefault("PATH", f"{Path.cwd() / 'tools' / 'maven' / 'apache-maven-3.9.6' / 'bin'}:{mvn_env['PATH']}")
        mvn_binary = shutil.which("mvn", path=mvn_env.get("PATH"))
        if mvn_binary:
            command = [mvn_binary, "-B", "-q", "test"]
            exit_code = run_command(command, java_dir, mvn_env, log_path)
            trace.append({
                "command": command,
                "cwd": str(java_dir),
                "exit_code": exit_code,
                "reports": str((java_dir / "target" / "surefire-reports").relative_to(Path.cwd())),
            })
            reports_dir = java_dir / "target" / "surefire-reports"
            if reports_dir.exists():
                java_reports_rel = str(reports_dir.relative_to(Path.cwd()))
        else:
            log_path.write_text("Maven binary not found; skipping Java execution.\n", encoding="utf-8")
            trace.append({
                "command": ["mvn", "-B", "-q", "test"],
                "cwd": str(java_dir),
                "exit_code": None,
                "skipped": "mvn not available",
            })

    (execution_dir / "trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")

    manifest_out = {
        "run_id": "RUN-FR014-EXEC",
        "generated_at": time_iso(),
        "artifacts": {
            "execution": {
                "python_junit": str((execution_dir / "junit_python.xml").relative_to(output_dir)) if python_tests else None,
                "java_reports": java_reports_rel,
                "trace": "execution/trace.json",
            },
            "logs": {
                "pytest": str((logs_dir / "pytest.log").relative_to(output_dir)) if python_tests else None,
                "maven": str((logs_dir / "maven.log").relative_to(output_dir)) if java_dir else None,
            },
        },
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest_out, indent=2) + "\n", encoding="utf-8")

    index_entries = []
    for path in output_dir.rglob('*'):
        if path.is_dir() or path.name == 'index.json':
            continue
        index_entries.append({
            "path": str(path.relative_to(output_dir)).replace('\\', '/'),
            "size_bytes": path.stat().st_size,
        })
    index = {
        "run_id": "RUN-FR014-EXEC",
        "generated_at": manifest_out["generated_at"],
        "artifacts": index_entries,
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def time_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute generated tests and capture artifacts.")
    parser.add_argument("manifest", type=Path, help="Path to tests/manifest.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Where to store orchestrator artifacts")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    orchestrate(args.manifest, args.output)


if __name__ == "__main__":
    main()
