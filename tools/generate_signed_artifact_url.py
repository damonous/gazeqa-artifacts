#!/usr/bin/env python3
"""Generate signed download URLs for artifacts."""
from __future__ import annotations

import argparse
import hmac
import hashlib
import time
from urllib.parse import quote


def sign_path(signing_key: str, run_id: str, path: str, expires: int) -> str:
    message = f"{run_id}:{path}:{expires}".encode("utf-8")
    return hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_url(base: str, run_id: str, path: str, expires: int, signature: str) -> str:
    quoted_path = quote(path)
    return f"{base}/runs/public/download?run_id={run_id}&path={quoted_path}&expires={expires}&signature={signature}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate signed artifact download URL")
    parser.add_argument("run_id")
    parser.add_argument("artifact_path", help="Relative path inside artifacts/runs/<id>/")
    parser.add_argument("signing_key", help="GAZEQA_SIGNING_KEY value")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--ttl", type=int, default=900, help="Time to live in seconds")
    args = parser.parse_args()

    expires = int(time.time()) + args.ttl
    signature = sign_path(args.signing_key, args.run_id, args.artifact_path, expires)
    url = build_url(args.base_url.rstrip('/'), args.run_id, args.artifact_path, expires, signature)
    print(url)


if __name__ == "__main__":
    main()
