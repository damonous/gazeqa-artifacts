"""Command-line interface for GazeQA run intake."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from .auth import build_auth_orchestrator
from .run_service import RunService, ValidationError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a GazeQA run from JSON payload")
    parser.add_argument("payload", type=Path, help="Path to JSON file describing the run request")
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path("artifacts/runs"),
        help="Directory where run manifests are written (default: artifacts/runs)",
    )
    return parser.parse_args(argv)


def load_payload(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Payload file not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in payload file: {exc}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    payload = load_payload(args.payload)
    auth_orchestrator = build_auth_orchestrator(args.storage_root)
    service = RunService(
        storage_root=args.storage_root,
        auth_orchestrator=auth_orchestrator,
    )
    try:
        run_record = service.create_run(payload)
    except ValidationError as exc:
        print("Failed to create run. See validation errors below:", file=sys.stderr)
        for field, message in exc.errors.items():
            print(f" - {field}: {message}", file=sys.stderr)
        raise SystemExit(1)
    else:
        print(json.dumps(run_record, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
