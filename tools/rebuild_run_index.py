#!/usr/bin/env python3
"""CLI utility to rebuild run_index.json and optionally migrate legacy directories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gazeqa.maintenance import rebuild_run_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild run_index.json for artifacts/runs storage")
    parser.add_argument(
        "storage_root",
        nargs="?",
        default="artifacts/runs",
        help="Path to the run storage root (default: artifacts/runs)",
    )
    parser.add_argument(
        "--move-legacy",
        action="store_true",
        help="Move legacy artifacts/runs/<RUN-ID>/ directories into org-specific folders",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the resulting index JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    storage_root = Path(args.storage_root)
    index = rebuild_run_index(storage_root, move_legacy=args.move_legacy)
    print(json.dumps(index, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
