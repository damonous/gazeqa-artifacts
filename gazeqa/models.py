"""Core data models for GazeQA run intake."""
from __future__ import annotations

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

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "CreateRunPayload":
        errors: Dict[str, str] = {}

        target_url = str(raw.get("target_url", ""))
        if not target_url:
            errors["target_url"] = "target_url is required"
        elif not _is_valid_url(target_url):
            errors["target_url"] = "target_url must include scheme and host"

        cred_raw = raw.get("credentials") or {}
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

        if errors:
            raise ValidationError(errors)

        return cls(
            target_url=target_url,
            credentials=credentials,
            budgets=budgets,
            storage_profile=storage_profile,
            tags=tags,
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
