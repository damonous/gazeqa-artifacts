"""Authentication orchestration and concrete integrations for FR-002."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

import requests

from .models import CredentialSpec

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when an authentication stage fails irrecoverably."""


@dataclass(slots=True)
class AuthAttempt:
    """Represents the outcome of a single authentication attempt."""

    success: bool
    storage_state: Optional[str]
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


AuthCallable = Callable[[str, CredentialSpec, "AuthConfig", Path, int], AuthAttempt]


@dataclass(slots=True)
class AuthConfig:
    """Configuration for authentication orchestration."""

    storage_root: Path = Path("artifacts/runs")
    timeout_seconds: int = 120
    allow_fallback: bool = True
    encryption_key: Optional[str] = field(default_factory=lambda: os.getenv("GAZEQA_AUTH_ENCRYPTION_KEY"))
    storage_filename: str = "storageState.json.enc"
    browserbase_api_key: Optional[str] = field(default_factory=lambda: os.getenv("BROWSERBASE_API_KEY"))
    browserbase_project_id: Optional[str] = field(default_factory=lambda: os.getenv("BROWSERBASE_PROJECT_ID"))
    browserbase_region: str = field(default_factory=lambda: os.getenv("BROWSERBASE_REGION", "us-east-1"))
    browserbase_start_url: Optional[str] = None
    browserbase_goal: Optional[str] = None
    success_selectors: Sequence[str] = ()
    fallback_login_url: Optional[str] = None
    username_selectors: Sequence[str] = (
        "input[name=username]",
        "input[type=email]",
        "input[name=email]",
    )
    password_selectors: Sequence[str] = ("input[name=password]", "input[type=password]")
    submit_selectors: Sequence[str] = ("button[type=submit]", "input[type=submit]")
    playwright_browser: str = "chromium"
    playwright_headless: bool = True

    def ensure_encryption_key(self) -> str:
        if not self.encryption_key:
            raise RuntimeError(
                "GAZEQA_AUTH_ENCRYPTION_KEY is required to encrypt storage state artifacts."
            )
        return self.encryption_key


class StorageEncryptor:
    """Encrypts storage state payloads before persistence."""

    def encrypt_and_write(self, plaintext: str, target: Path) -> Path:  # pragma: no cover - interface
        raise NotImplementedError


class FernetStorageEncryptor(StorageEncryptor):
    """Encrypts storage state using Fernet symmetric encryption."""

    def __init__(self, key: str) -> None:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "cryptography package required for storage state encryption"
            ) from exc
        key_bytes = key.encode("utf-8") if isinstance(key, str) else key
        self._fernet = Fernet(key_bytes)

    def encrypt_and_write(self, plaintext: str, target: Path) -> Path:
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(token)
        return target

    def decrypt(self, source: Path) -> str:
        payload = source.read_bytes()
        return self._fernet.decrypt(payload).decode("utf-8")


class PlaintextStorageWriter(StorageEncryptor):
    """Fallback writer that stores plaintext (discouraged)."""

    def encrypt_and_write(self, plaintext: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plaintext, encoding="utf-8")
        return target


def generate_encryption_key() -> str:
    """Generate a new Fernet-compatible encryption key."""

    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


class AuthenticationOrchestrator:
    """Coordinates CUA-first authentication with scripted fallback."""

    def __init__(
        self,
        cua_login: AuthCallable,
        fallback_login: AuthCallable,
        config: AuthConfig | None = None,
        storage_encryptor: StorageEncryptor | None = None,
    ) -> None:
        self.config = config or AuthConfig()
        encryption_key = self.config.ensure_encryption_key()
        self.storage_encryptor = storage_encryptor or FernetStorageEncryptor(encryption_key)
        self.cua_login = cua_login
        self.fallback_login = fallback_login

    def authenticate(self, run_id: str, credentials: CredentialSpec) -> dict[str, Any]:
        evidence_dir = self._ensure_evidence_dir(run_id)
        attempts_log: list[dict[str, Any]] = []

        cua_attempt = self._execute_stage(
            "cua", self.cua_login, run_id, credentials, evidence_dir
        )
        attempts_log.append(self._attempt_to_dict("cua", cua_attempt))

        final_stage = "cua"
        final_attempt = cua_attempt
        if not cua_attempt.success and self.config.allow_fallback:
            fallback_attempt = self._execute_stage(
                "fallback", self.fallback_login, run_id, credentials, evidence_dir
            )
            attempts_log.append(self._attempt_to_dict("fallback", fallback_attempt))
            final_stage = "fallback"
            final_attempt = fallback_attempt

        result: dict[str, Any] = {
            "run_id": run_id,
            "stage": final_stage,
            "success": final_attempt.success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "storage_state_path": None,
            "evidence": list(final_attempt.evidence),
            "metadata": final_attempt.metadata,
            "attempts": attempts_log,
        }

        if final_attempt.success and final_attempt.storage_state:
            storage_path = evidence_dir / self.config.storage_filename
            stored_path = self.storage_encryptor.encrypt_and_write(
                final_attempt.storage_state, storage_path
            )
            result["storage_state_path"] = str(stored_path)
        if final_attempt.error:
            result["error"] = final_attempt.error
        self._persist_log(evidence_dir, result)
        return result

    def _execute_stage(
        self,
        stage: str,
        callable_: AuthCallable,
        run_id: str,
        credentials: CredentialSpec,
        evidence_dir: Path,
    ) -> AuthAttempt:
        try:
            return callable_(
                run_id,
                credentials,
                self.config,
                evidence_dir,
                self.config.timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Authentication stage %s raised an exception", stage)
            return AuthAttempt(success=False, storage_state=None, error=str(exc))

    def _ensure_evidence_dir(self, run_id: str) -> Path:
        path = self.config.storage_root / run_id / "auth"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _persist_log(self, evidence_dir: Path, result: dict[str, Any]) -> None:
        log_path = evidence_dir / "auth_result.json"
        log_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    @staticmethod
    def _attempt_to_dict(stage: str, attempt: AuthAttempt) -> dict[str, Any]:
        return {
            "stage": stage,
            "success": attempt.success,
            "evidence": attempt.evidence,
            "metadata": attempt.metadata,
            "error": attempt.error,
        }


# ---------------------------------------------------------------------------
# Browserbase (CUA) integration
# ---------------------------------------------------------------------------


_BROWSERBASE_API_BASE = "https://api.browserbase.com/v1"


def browserbase_cua_login(
    run_id: str,
    credentials: CredentialSpec,
    config: AuthConfig,
    evidence_dir: Path,
    timeout: int,
) -> AuthAttempt:
    """Attempt to authenticate using Browserbase CUA sessions."""

    if not config.browserbase_api_key or not config.browserbase_project_id:
        return AuthAttempt(
            success=False,
            storage_state=None,
            error="Browserbase credentials not configured",
        )
    if not config.browserbase_start_url:
        return AuthAttempt(
            success=False,
            storage_state=None,
            error="browserbase_start_url missing from AuthConfig",
        )

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {config.browserbase_api_key}",
            "Content-Type": "application/json",
        }
    )

    payload: Dict[str, Any] = {
        "project_id": config.browserbase_project_id,
        "region": config.browserbase_region or "us-east-1",
        "name": f"auth-{run_id}",
        "start_url": config.browserbase_start_url,
        "timeout": timeout,
        "metadata": {"run_id": run_id, "stage": "auth"},
        "goal": config.browserbase_goal
        or "Authenticate the provided user and persist storage state.",
        "context": {
            "credentials": {
                "username": credentials.username,
                "password": credentials.secret_ref,
            },
            "successSelectors": list(config.success_selectors),
        },
    }

    try:
        create_resp = session.post(
            f"{_BROWSERBASE_API_BASE}/sessions",
            json=payload,
            timeout=timeout,
        )
        create_resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Browserbase session creation failed: %s", exc)
        return AuthAttempt(success=False, storage_state=None, error=str(exc))

    session_info = create_resp.json()
    session_id = session_info.get("id")
    if not session_id:
        return AuthAttempt(success=False, storage_state=None, error="Missing Browserbase session id")

    status = session_info.get("status")
    deadline = time.time() + timeout
    while status not in {"completed", "failed", "timeout"} and time.time() < deadline:
        time.sleep(3)
        try:
            status_resp = session.get(
                f"{_BROWSERBASE_API_BASE}/sessions/{session_id}", timeout=15
            )
            status_resp.raise_for_status()
            status_info = status_resp.json()
            status = status_info.get("status")
        except requests.RequestException as exc:  # pragma: no cover - network noise
            logger.warning("Polling Browserbase session failed: %s", exc)
            status = "failed"
            break

    metadata = {"session_id": session_id, "status": status}
    if status != "completed":
        return AuthAttempt(success=False, storage_state=None, metadata=metadata)

    storage_state: Optional[str] = None
    try:
        storage_resp = session.get(
            f"{_BROWSERBASE_API_BASE}/sessions/{session_id}/storage-state",
            timeout=30,
        )
        storage_resp.raise_for_status()
        storage_state = storage_resp.text
    except requests.RequestException as exc:
        logger.error("Fetching Browserbase storage state failed: %s", exc)
        return AuthAttempt(success=False, storage_state=None, error=str(exc), metadata=metadata)

    evidence: list[str] = []
    try:
        screenshot_resp = session.get(
            f"{_BROWSERBASE_API_BASE}/sessions/{session_id}/screenshot",
            timeout=30,
        )
        if screenshot_resp.ok:
            screenshot_path = evidence_dir / f"browserbase_final_{session_id}.png"
            screenshot_path.write_bytes(screenshot_resp.content)
            evidence.append(str(screenshot_path))
    except requests.RequestException as exc:  # pragma: no cover - evidence optional
        logger.warning("Browserbase screenshot retrieval failed: %s", exc)

    return AuthAttempt(
        success=True,
        storage_state=storage_state,
        evidence=evidence,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Playwright fallback integration
# ---------------------------------------------------------------------------


def playwright_fallback_login(
    run_id: str,
    credentials: CredentialSpec,
    config: AuthConfig,
    evidence_dir: Path,
    timeout: int,
) -> AuthAttempt:
    """Execute a scripted Playwright login as a fallback path."""

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return AuthAttempt(
            success=False,
            storage_state=None,
            error="Playwright not installed",
        )

    login_url = config.fallback_login_url or config.browserbase_start_url
    if not login_url:
        return AuthAttempt(success=False, storage_state=None, error="No login URL configured")
    if not credentials.secret_ref:
        return AuthAttempt(success=False, storage_state=None, error="secret_ref missing for fallback login")

    evidence: list[str] = []
    metadata: dict[str, Any] = {"browser": config.playwright_browser}

    try:
        with sync_playwright() as p:
            browser_type = getattr(p, config.playwright_browser)
            browser = browser_type.launch(headless=config.playwright_headless)
            context = browser.new_context()
            page = context.new_page()
            page.goto(login_url, wait_until="networkidle", timeout=timeout * 1000)

            _fill_first_selector(page, config.username_selectors, credentials.username or "")
            _fill_first_selector(page, config.password_selectors, credentials.secret_ref)
            _click_first_selector(page, config.submit_selectors)

            for selector in config.success_selectors:
                try:
                    page.wait_for_selector(selector, timeout=max(1000, timeout * 500))
                except PlaywrightTimeoutError:
                    metadata.setdefault("missing_selectors", []).append(selector)

            storage_state_dict = context.storage_state()
            storage_state = json.dumps(storage_state_dict)

            screenshot_path = evidence_dir / "playwright_post_login.png"
            page.screenshot(path=screenshot_path)
            evidence.append(str(screenshot_path))

            browser.close()
    except PlaywrightTimeoutError as exc:
        return AuthAttempt(success=False, storage_state=None, error=str(exc), metadata=metadata)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Playwright fallback failed")
        return AuthAttempt(success=False, storage_state=None, error=str(exc))

    return AuthAttempt(success=True, storage_state=storage_state, evidence=evidence, metadata=metadata)


def _fill_first_selector(page: Any, selectors: Iterable[str], value: str) -> None:
    for selector in selectors:
        try:
            page.fill(selector, value)
            return
        except Exception:  # pragma: no cover - attempt next selector
            continue
    raise AuthenticationError(f"Unable to fill any selector from {selectors}")


def _click_first_selector(page: Any, selectors: Iterable[str]) -> None:
    for selector in selectors:
        try:
            page.click(selector)
            return
        except Exception:  # pragma: no cover - try next selector
            continue
    raise AuthenticationError(f"Unable to click any selector from {selectors}")


def decrypt_storage_state(path: str | Path, key: Optional[str] = None) -> str:
    """Decrypt an encrypted storageState artifact using the provided key."""

    from cryptography.fernet import Fernet

    resolved_key = key or os.getenv("GAZEQA_AUTH_ENCRYPTION_KEY")
    if not resolved_key:
        raise RuntimeError("Encryption key required to decrypt storage state.")
    fernet = Fernet(resolved_key.encode() if isinstance(resolved_key, str) else resolved_key)
    payload = Path(path).read_bytes()
    return fernet.decrypt(payload).decode("utf-8")


def build_auth_orchestrator(storage_root: Path) -> Optional[AuthenticationOrchestrator]:
    """Construct the default orchestrator if required secrets are configured."""

    if not os.getenv("GAZEQA_AUTH_ENCRYPTION_KEY"):
        logger.info("Authentication orchestrator disabled: encryption key not set")
        return None
    config = AuthConfig(storage_root=storage_root)
    try:
        return AuthenticationOrchestrator(
            browserbase_cua_login,
            playwright_fallback_login,
            config=config,
        )
    except RuntimeError as exc:
        logger.warning("Authentication orchestrator disabled: %s", exc)
        return None


__all__ = [
    "AuthenticationOrchestrator",
    "AuthConfig",
    "AuthAttempt",
    "browserbase_cua_login",
    "playwright_fallback_login",
    "generate_encryption_key",
    "FernetStorageEncryptor",
    "decrypt_storage_state",
    "build_auth_orchestrator",
]
