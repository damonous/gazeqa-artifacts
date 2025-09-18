# Security Controls (FR-017 Draft)

- **Authentication**: All API endpoints require a bearer token (`GAZEQA_API_TOKEN`). SSE endpoints accept the same token via `Authorization` header or `token` query param for EventSource clients.
- **Secrets management**: Store credentials/`storageState.json` encrypted. Integrate with Vault/KMS before production.
- **Audit trail**: `run_manifest.json`, `status_history.json`, and `events.jsonl` form the audit baseline; long term ship to centralized logging.
- **Artifact access**: When exposing beyond the CLI/UI, wrap `artifacts/index.json` with signed URLs. Current endpoints return metadata only.
- **CORS & transport**: Enable TLS and restrict origins when hosting the Lovable dashboard.
- **Deployment hardening**: Terminate TLS at reverse proxy (nginx/Traefik); enforce CORS for Lovable's origin; rotate tokens via env/secret manager.
- Signed URL helper: use `tools/generate_signed_artifact_url.py` during support triage; never expose raw paths without signatures.

