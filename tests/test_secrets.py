from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gazeqa.security import SecretsManager


def test_token_registry_file_reload(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps({"token-1": {"organization": "default"}}), encoding="utf-8")
    manager = SecretsManager(default_token=None, registry_file=registry_file)
    registry = manager.get_token_registry()
    assert "token-1" in registry

    registry_file.write_text(
        json.dumps({"token-2": {"organization": "Acme", "organization_slug": "acme"}}),
        encoding="utf-8",
    )
    future = time.time() + 2
    os.utime(registry_file, (future, future))
    updated = manager.get_token_registry()
    assert "token-2" in updated
    assert "token-1" not in updated


def test_token_file_defaults_and_reload(tmp_path: Path) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("rotating-token", encoding="utf-8")
    manager = SecretsManager(
        default_token=None,
        token_file=token_file,
        token_file_defaults={
            "organization": "Acme",
            "organization_slug": "acme",
            "actor_role": "admin",
        },
    )
    registry = manager.get_token_registry()
    assert "rotating-token" in registry
    assert registry["rotating-token"]["actor_role"] == "admin"

    token_file.write_text("next-token", encoding="utf-8")
    future = time.time() + 2
    os.utime(token_file, (future, future))
    rotated = manager.get_token_registry()
    assert "next-token" in rotated
    assert "rotating-token" not in rotated


def test_signing_key_file_reload(tmp_path: Path) -> None:
    key_file = tmp_path / "signing.keys"
    key_file.write_text("primary-key\nbackup-key\n", encoding="utf-8")
    manager = SecretsManager(default_token=None, signing_key_file=key_file)
    keys = manager.get_signing_keys()
    assert keys.primary == "primary-key"
    assert keys.all_keys == ("primary-key", "backup-key")

    key_file.write_text("rotated-key\nold-key\n", encoding="utf-8")
    os.utime(key_file, (time.time() + 1, time.time() + 1))
    rotated = manager.get_signing_keys()
    assert rotated.primary == "rotated-key"
    assert rotated.all_keys[0] == "rotated-key"
    assert "old-key" in rotated.all_keys
