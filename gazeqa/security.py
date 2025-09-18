"""Security helpers: token registry normalization and secret reloading."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

ROLE_DEFAULT_SCOPES: dict[str, set[str]] = {
    "qa_runner": {"runs:create", "runs:read", "runs:events"},
    "qa_viewer": {"runs:read", "runs:events"},
    "admin": {"runs:create", "runs:read", "runs:events", "runs:read:all"},
}

DEFAULT_OPEN_SCOPES = {"runs:create", "runs:read", "runs:events", "runs:read:all"}


def scopes_for_role(role: str) -> list[str]:
    """Return the default scope list for a role."""

    fallback = ROLE_DEFAULT_SCOPES.get("qa_viewer", set())
    scopes = ROLE_DEFAULT_SCOPES.get(role, fallback)
    return sorted(scopes)


def normalize_registry_entry(token: str, value: object) -> Optional[dict[str, Any]]:
    """Normalize a token registry entry structure."""

    if not isinstance(value, dict):
        logger.warning("Token registry entry for %s is not an object", token)
        return None
    organization = str(
        value.get("organization")
        or value.get("organization_name")
        or value.get("organization_slug")
        or "default"
    ).strip()
    organization_slug = (
        str(value.get("organization_slug") or organization or "default").strip() or "default"
    )
    actor_role = str(value.get("actor_role") or "qa_viewer").strip() or "qa_viewer"
    scopes_raw = value.get("scopes")
    if isinstance(scopes_raw, (list, tuple, set)):
        scopes = sorted({str(item).strip() for item in scopes_raw if item})
    else:
        scopes = scopes_for_role(actor_role)
    return {
        "organization": organization or organization_slug,
        "organization_slug": organization_slug,
        "actor_role": actor_role,
        "scopes": scopes,
    }


def load_token_registry(
    default_token: Optional[str],
    registry_json: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    """Load the token registry from JSON with optional default token."""

    registry: dict[str, dict[str, Any]] = {}
    raw = registry_json if registry_json is not None else os.getenv("GAZEQA_API_TOKEN_REGISTRY")
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse token registry JSON; ignoring")
        else:
            if isinstance(parsed, dict):
                for token, value in parsed.items():
                    normalized = normalize_registry_entry(str(token), value)
                    if normalized:
                        registry[str(token)] = normalized
            else:
                logger.warning("Token registry JSON must be an object mapping tokens to metadata")
    if default_token and default_token not in registry:
        registry[default_token] = {
            "organization": "default",
            "organization_slug": "default",
            "actor_role": "qa_runner",
            "scopes": scopes_for_role("qa_runner"),
        }
    return registry


@dataclass(frozen=True)
class SigningKeySet:
    """Represents the active signing key and verification set."""

    primary: Optional[str]
    all_keys: tuple[str, ...]


class SecretsManager:
    """Hot-reloads API tokens and signing keys from files."""

    def __init__(
        self,
        *,
        default_token: Optional[str],
        registry_json: Optional[str] = None,
        registry_file: str | Path | None = None,
        token_file: str | Path | None = None,
        token_file_defaults: Optional[dict[str, str]] = None,
        signing_key: Optional[str] = None,
        signing_key_previous: Iterable[str] | None = None,
        signing_key_file: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._base_registry = load_token_registry(default_token, registry_json)
        self._registry_file = Path(registry_file) if registry_file else None
        self._registry_file_mtime: float | None = None
        self._registry_override: dict[str, dict[str, Any]] = {}

        self._token_file = Path(token_file) if token_file else None
        self._token_file_mtime: float | None = None
        self._token_file_entry: dict[str, dict[str, Any]] = {}
        self._token_defaults = token_file_defaults or {
            "organization": "default",
            "organization_slug": "default",
            "actor_role": "qa_runner",
        }

        self._primary_signing_key = signing_key or None
        self._previous_signing_keys = tuple(
            key.strip() for key in (signing_key_previous or ()) if key and key.strip()
        )
        self._signing_key_file = Path(signing_key_file) if signing_key_file else None
        self._signing_key_file_mtime: float | None = None
        self._signing_key_file_keys: tuple[str, ...] = ()

    # ------------------------------------------------------------------ tokens
    def get_token_registry(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            self._refresh_token_sources_locked()
            return self._compose_registry_locked()

    def _refresh_token_sources_locked(self) -> None:
        if self._registry_file:
            try:
                stat = self._registry_file.stat()
            except FileNotFoundError:
                if self._registry_override:
                    logger.warning("Token registry file disappeared: %s", self._registry_file)
                    self._registry_override = {}
                self._registry_file_mtime = None
            else:
                if self._registry_file_mtime != stat.st_mtime:
                    self._registry_override = self._load_registry_override()
                    self._registry_file_mtime = stat.st_mtime
        if self._token_file:
            try:
                stat = self._token_file.stat()
            except FileNotFoundError:
                if self._token_file_entry:
                    logger.warning("Token file disappeared: %s", self._token_file)
                    self._token_file_entry = {}
                self._token_file_mtime = None
            else:
                if self._token_file_mtime != stat.st_mtime:
                    self._token_file_entry = self._load_token_file_entry()
                    self._token_file_mtime = stat.st_mtime

    def _compose_registry_locked(self) -> dict[str, dict[str, Any]]:
        registry = dict(self._base_registry)
        if self._token_file_entry:
            registry.update(self._token_file_entry)
        if self._registry_override:
            registry.update(self._registry_override)
        return registry

    def _load_registry_override(self) -> dict[str, dict[str, Any]]:
        try:
            raw = self._registry_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to read token registry file %s: %s", self._registry_file, exc)
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in token registry file %s: %s", self._registry_file, exc)
            return {}
        if not isinstance(parsed, dict):
            logger.error("Token registry file %s must contain a JSON object", self._registry_file)
            return {}
        overrides: dict[str, dict[str, Any]] = {}
        for token, value in parsed.items():
            normalized = normalize_registry_entry(str(token), value)
            if normalized:
                overrides[str(token)] = normalized
        return overrides

    def _load_token_file_entry(self) -> dict[str, dict[str, Any]]:
        try:
            token = self._token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.error("Failed to read token file %s: %s", self._token_file, exc)
            return {}
        if not token:
            return {}
        metadata = {
            "organization": self._token_defaults.get("organization", "default"),
            "organization_slug": self._token_defaults.get("organization_slug", "default"),
            "actor_role": self._token_defaults.get("actor_role", "qa_runner"),
        }
        metadata["scopes"] = scopes_for_role(str(metadata["actor_role"]))
        return {token: metadata}

    # ----------------------------------------------------------- signing keys
    def get_signing_keys(self) -> SigningKeySet:
        with self._lock:
            self._refresh_signing_keys_locked()
            primary, all_keys = self._compose_signing_keys_locked()
        return SigningKeySet(primary=primary, all_keys=all_keys)

    def _refresh_signing_keys_locked(self) -> None:
        if not self._signing_key_file:
            return
        try:
            stat = self._signing_key_file.stat()
        except FileNotFoundError:
            if self._signing_key_file_keys:
                logger.warning("Signing key file disappeared: %s", self._signing_key_file)
                self._signing_key_file_keys = ()
            self._signing_key_file_mtime = None
        else:
            if self._signing_key_file_mtime != stat.st_mtime:
                self._signing_key_file_keys = self._load_signing_key_file()
                self._signing_key_file_mtime = stat.st_mtime

    def _load_signing_key_file(self) -> tuple[str, ...]:
        try:
            raw = self._signing_key_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to read signing key file %s: %s", self._signing_key_file, exc)
            return ()
        keys = [line.strip() for line in raw.splitlines() if line.strip()]
        return tuple(dict.fromkeys(keys))  # preserve order, drop duplicates

    def _compose_signing_keys_locked(self) -> tuple[Optional[str], tuple[str, ...]]:
        keys: list[str] = []
        if self._signing_key_file_keys:
            keys.extend(self._signing_key_file_keys)
        elif self._primary_signing_key:
            keys.append(self._primary_signing_key)
        for key in self._previous_signing_keys:
            if key and key not in keys:
                keys.append(key)
        primary = keys[0] if keys else None
        return primary, tuple(keys)


__all__ = [
    "ROLE_DEFAULT_SCOPES",
    "DEFAULT_OPEN_SCOPES",
    "SecretsManager",
    "SigningKeySet",
    "normalize_registry_entry",
    "load_token_registry",
    "scopes_for_role",
]
