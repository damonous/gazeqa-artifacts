# Authentication Prototype (FR-002)

`gazeqa.auth.AuthenticationOrchestrator` demonstrates the login flow:

- Call `authenticate(run_id, CredentialSpec)` with pre-validated credentials.
- The orchestrator first invokes the provided **CUA login callable** (`browserbase_cua_login` by default). If it returns success, the storage state JSON is encrypted with the Fernet key referenced by `GAZEQA_AUTH_ENCRYPTION_KEY` and written as `storageState.json.enc` under `artifacts/runs/<RUN-ID>/auth/`.
- If the CUA login fails and `allow_fallback` is true, the **fallback login callable** (`playwright_fallback_login`) executes. Its storage state output is encrypted the same way.
- `auth_result.json` captures the stage (`cua` or `fallback`), success flag, evidence paths (screenshots, logs), metadata, and the encrypted storageState path.

## Sample Usage

```python
from gazeqa.auth import (
    AuthenticationOrchestrator,
    AuthConfig,
    browserbase_cua_login,
    playwright_fallback_login,
)
from gazeqa.models import CredentialSpec

config = AuthConfig(
    browserbase_start_url="https://alpha-stage.example/login",
    success_selectors=("#dashboard",),
)
orchestrator = AuthenticationOrchestrator(
    browserbase_cua_login,
    playwright_fallback_login,
    config,
)
result = orchestrator.authenticate("RUN-ABC123", CredentialSpec(username="qa@example.com", secret_ref="vault://123"))
```

Both callables expect that `CredentialSpec.secret_ref` resolves to a usable secret (password) before invocation. Each callable returns an `AuthAttempt` containing the success flag, storage state JSON, structured evidence, and metadata (session ids, browser name, etc.).

## Tests

- `tests/test_auth.py` uses fake callables to exercise both the success and fallback flows, satisfying FR-002 acceptance criteria scaffolding.

Next steps for Agent Alpha:
1. Provide secret resolution before invoking the orchestrator so Browserbase/Playwright receive real credentials.
2. Extend selector configuration (`AuthConfig.username_selectors`, etc.) as new targets are onboarded.
3. Wire session vault retrieval to decrypt `storageState.json.enc` when downstream explorers require it.
