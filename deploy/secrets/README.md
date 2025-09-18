# Local Secret Placeholders

These files exist so docker compose can mount predictable paths. **Replace every placeholder before running in any non-dev environment.**

- `api/tokens/registry.json` — map bearer tokens to org metadata.
- `api/tokens/default.token` — single-token fallback (optional).
- `api/keys/signing.keys` — first line is the active artifact signing key; subsequent lines may include previous keys for signature verification.
- `alertmanager/alert_webhook_token` — bearer token Alertmanager will send when POSTing to `/observability/alerts`.
- `tls/` — drop `api.pem` / `api-key.pem` (or update env vars) if terminating TLS in the container.

Commit-safe placeholders make it obvious that these values are not production ready.
