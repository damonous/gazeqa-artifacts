import json
import shutil
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from gazeqa.auth import (
    AuthAttempt,
    AuthenticationOrchestrator,
    AuthConfig,
    decrypt_storage_state,
)
from gazeqa.models import CredentialSpec


def fake_cua(run_id, credentials, config, evidence_dir, timeout):
    evidence_path = evidence_dir / "cua.log"
    evidence_path.write_text("CUA attempt", encoding="utf-8")
    if credentials.username == "fail@cua" or not credentials.secret_ref:
        return AuthAttempt(success=False, storage_state=None, evidence=[str(evidence_path)])
    storage_state = json.dumps({"cookies": ["session=abc"]})
    return AuthAttempt(success=True, storage_state=storage_state, evidence=[str(evidence_path)])


def fake_fallback(run_id, credentials, config, evidence_dir, timeout):
    evidence_path = evidence_dir / "fallback.log"
    evidence_path.write_text("Fallback attempt", encoding="utf-8")
    storage_state = json.dumps({"cookies": ["fallback=session"]})
    return AuthAttempt(success=True, storage_state=storage_state, evidence=[str(evidence_path)])


@pytest.fixture()
def temp_root():
    temp = Path(tempfile.mkdtemp())
    try:
        yield temp
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def build_config(temp_root: Path) -> AuthConfig:
    return AuthConfig(
        storage_root=temp_root,
        encryption_key=Fernet.generate_key().decode(),
        browserbase_start_url="https://example.test/login",
        success_selectors=("#dashboard",),
    )


def test_auth_success_primary(temp_root: Path):
    config = build_config(temp_root)
    orchestrator = AuthenticationOrchestrator(fake_cua, fake_fallback, config)
    creds = CredentialSpec(username="qa@example.com", secret_ref="secret-value")

    result = orchestrator.authenticate("RUN-TEST", creds)

    assert result["success"] is True
    auth_dir = temp_root / "RUN-TEST" / "auth"
    encrypted_path = auth_dir / config.storage_filename
    assert encrypted_path.exists()

    decrypted = decrypt_storage_state(encrypted_path, config.encryption_key)
    assert "session=abc" in decrypted


def test_auth_fallback(temp_root: Path):
    config = build_config(temp_root)
    orchestrator = AuthenticationOrchestrator(fake_cua, fake_fallback, config)
    creds = CredentialSpec(username="fail@cua", secret_ref="secret-value")

    result = orchestrator.authenticate("RUN-TEST", creds)

    assert result["stage"] == "fallback"
    assert result["success"] is True
