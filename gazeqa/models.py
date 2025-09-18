"""Core data models for GazeQA run intake."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse


class ValidationError(Exception):
    """Raised when payload validation fails."""

    def __init__(self, errors: Dict[str, str]):
        super().__init__("Payload validation failed")
        self.errors = errors

    def __str__(self) -> str:  # pragma: no cover - debug convenience
        return f"ValidationError(errors={self.errors!r})"


@dataclass(slots=True)
class CredentialSpec:
    username: Optional[str] = None
    secret_ref: Optional[str] = None

    def is_empty(self) -> bool:
        return not (self.username or self.secret_ref)


@dataclass(slots=True)
class BudgetSpec:
    time_budget_minutes: int = 30
    page_budget: int = 200


@dataclass(slots=True)
class CreateRunPayload:
    """Normalized CreateRun payload."""

    target_url: str
    credentials: CredentialSpec = field(default_factory=CredentialSpec)
    budgets: BudgetSpec = field(default_factory=BudgetSpec)
    storage_profile: str = "default"
    tags: List[str] = field(default_factory=list)
    organization: str = "default"
    organization_slug: str = "default"
    actor_role: str = "qa_runner"

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "CreateRunPayload":
        errors: Dict[str, str] = {}

        target_url = str(raw.get("target_url", ""))
        if not target_url:
            errors["target_url"] = "target_url is required"
        elif not _is_valid_url(target_url):
            errors["target_url"] = "target_url must include scheme and host"

        cred_raw = raw.get("credentials") or {}
        if isinstance(cred_raw, dict) and cred_raw and not any(cred_raw.values()):
            cred_raw = {}
        if not isinstance(cred_raw, dict):
            errors["credentials"] = "credentials must be an object"
            cred_raw = {}
        credentials = CredentialSpec(
            username=str(cred_raw.get("username")) if cred_raw.get("username") else None,
            secret_ref=str(cred_raw.get("secret_ref")) if cred_raw.get("secret_ref") else None,
        )
        if cred_raw and credentials.is_empty():
            errors["credentials.secret_ref"] = "secret_ref required when credentials supplied"

        budgets_raw = raw.get("budgets") or {}
        if not isinstance(budgets_raw, dict):
            errors["budgets"] = "budgets must be an object"
            budgets_raw = {}
        time_budget_minutes = _coerce_int(budgets_raw.get("time_budget_minutes"), default=30)
        page_budget = _coerce_int(budgets_raw.get("page_budget"), default=200)
        if time_budget_minutes <= 0:
            errors["budgets.time_budget_minutes"] = "must be > 0"
        if page_budget <= 0:
            errors["budgets.page_budget"] = "must be > 0"
        budgets = BudgetSpec(time_budget_minutes=time_budget_minutes, page_budget=page_budget)

        storage_profile = str(raw.get("storage_profile") or "default")
        tags_raw = raw.get("tags") or []
        if isinstance(tags_raw, list):
            tags = [str(tag) for tag in tags_raw]
        else:
            errors["tags"] = "tags must be an array"
            tags = []

        organization = str(raw.get("organization") or "").strip() or "default"
        slug_input = str(raw.get("organization_slug") or "").strip()
        if slug_input:
            try:
                organization_slug = _normalize_slug(slug_input)
            except ValueError as exc:
                errors["organization_slug"] = str(exc)
                organization_slug = "default"
        else:
            organization_slug = _normalize_slug(organization) if organization != "default" else "default"

        actor_role_raw = str(raw.get("actor_role") or "qa_runner").strip()
        if not actor_role_raw:
            errors["actor_role"] = "actor_role must not be empty"
            actor_role = "qa_runner"
        else:
            actor_role = actor_role_raw

        if errors:
            raise ValidationError(errors)

        return cls(
            target_url=target_url,
            credentials=credentials,
            budgets=budgets,
            storage_profile=storage_profile,
            tags=tags,
            organization=organization,
            organization_slug=organization_slug,
            actor_role=actor_role,
        )


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _coerce_int(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug:
        return "default"
    slug = slug.replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise ValueError("organization_slug must contain alphanumeric characters")
    if not _SLUG_PATTERN.match(slug):
        raise ValueError("organization_slug may contain lowercase letters, numbers, and hyphens")
    return slug
