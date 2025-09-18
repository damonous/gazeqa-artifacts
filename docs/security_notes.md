# Security Controls (FR-017 Draft)

- **Authentication**: All API endpoints require a bearer token (`GAZEQA_API_TOKEN`). SSE endpoints accept the same token via `Authorization` header or `token` query param for EventSource clients.
- **Secrets management**: Store credentials/`storageState.json` encrypted. Integrate with Vault/KMS before production.
- **Audit trail**: `run_manifest.json`, `status_history.json`, and `events.jsonl` form the audit baseline; long term ship to centralized logging.
- **Artifact access**: Signed download URLs are enforced via `GAZEQA_SIGNING_KEY` (or the hot-reloadable `GAZEQA_SIGNING_KEY_FILE`). Public downloads require HMAC signatures that expire after `GAZEQA_SIGNING_TTL` seconds.
- **Audit logging**: All run mutations, artifact downloads, and alert webhooks emit JSONL records under `<storage_root>/_audit/audit.log.jsonl`. `token_hash` fields are SHA-256 truncated fingerprints.
- **Secrets management**: `GAZEQA_TOKEN_REGISTRY_FILE` and `GAZEQA_API_TOKEN_FILE` enable hot-rotating API tokens; signing keys can be rotated without restart via `GAZEQA_SIGNING_KEY_FILE` with optional `GAZEQA_SIGNING_KEY_PREVIOUS` fallback list.
- **CORS & transport**: Restrict Lovable origins with `GAZEQA_ALLOWED_ORIGINS` and, when certs are mounted, enable on-process TLS using `GAZEQA_TLS_CERTFILE`/`GAZEQA_TLS_KEYFILE` or terminate at nginx/Traefik.
- **Alert intake**: Alertmanager routes webhook payloads to `/observability/alerts`; set `GAZEQA_ALERT_WEBHOOK_TOKEN` (and configure Alertmanager `authorization.credentials_file`) to require Bearer auth. Alerts are captured in the audit log with summaries.
- Signed URL helper: use `tools/generate_signed_artifact_url.py` during support triage; never expose raw paths without signatures.
- **Secret storage**: `deploy/secrets/` ships with placeholders so compose mounts resolve. Replace them with vault-managed files (or mount from a secrets volume) before shipping.
