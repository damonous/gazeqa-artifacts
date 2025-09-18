# Hetzner Deployment Guide

This guide explains how to run the GazeQA stack (API, worker, Temporal, Postgres, Redis, Prometheus, Grafana) on a Hetzner Ubuntu VM using Docker Compose. The Lovable frontend is hosted separately.

## 1. VM Preparation
1. Provision an Ubuntu 22.04 instance.
2. Harden the host (SSH keys only, firewall `ufw allow 22 80 443 8000 7233 8088 9090 3000`).
3. Install Docker & Compose:
   ```bash
   sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
   sudo install -m 0755 -d /etc/apt/keyrings
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
   sudo usermod -aG docker $USER
   ```
   Logout/login so `$USER` can run docker.

## 2. Clone Repo & Configure Env
```bash
mkdir -p ~/gazeqa && cd ~/gazeqa
https://github.com/damonous/gazeqa-cli-agents.git
cd gazeqa-cli-agents
cp deploy/env.example deploy/.env
vim deploy/.env   # update DB password, API token, Grafana creds
```

Optional `.env` hardening knobs:
- `GAZEQA_ALLOWED_ORIGINS` with the Lovable dashboard origin
- `GAZEQA_TLS_CERTFILE` / `GAZEQA_TLS_KEYFILE` when mounting certs directly into the API container
- `GAZEQA_TOKEN_REGISTRY_FILE`, `GAZEQA_API_TOKEN_FILE`, and `GAZEQA_SIGNING_KEY_FILE` for hot-rotated credentials
- `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` to forward workflow spans to Langfuse
- `GAZEQA_ALERT_WEBHOOK_TOKEN` so Alertmanager webhooks must present a bearer token

## 3. Build Images
Run from repo root:
```bash
docker compose -f deploy/docker-compose.yml build api worker
```
This builds custom images using `deploy/Dockerfile.api` and `deploy/Dockerfile.worker`.

## 4. Start Services
```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
```
Services:
- `gazeqa-api`: REST/SSE API on port 8000
- `gazeqa-worker`: Temporal worker placeholder
- `postgres`, `redis`, `temporal`, `temporal-ui`
- `prometheus` (9090) + `grafana` (3000)

Check container status:
```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs -f api
```

## 5. Reverse Proxy & TLS
Use nginx/traefik on the VM (outside compose) to terminate TLS and forward to:
- `api`: http://127.0.0.1:8000
- `temporal-ui`: http://127.0.0.1:8088
- `grafana`: http://127.0.0.1:3000 (optional)
Update nginx server blocks with Let’s Encrypt certs and set `GAZEQA_API_TOKEN` for Lovable.
If you choose to terminate TLS inside the container, mount the certificate/key and set `GAZEQA_TLS_CERTFILE` / `GAZEQA_TLS_KEYFILE` in `.env`.

## 6. Secrets & Storage
- `artifacts-data` volume holds run artefacts.
- Use Hetzner volumes or S3-compatible storage if persistent data must survive re-provisioning.
- Manage secrets with environment variables or integrate Vault/KMS (see `docs/security_notes.md`).
  - Provide token/registry/signing key files at the paths referenced by the env vars above to rotate secrets without restarting containers.
  - Replace every placeholder file under `deploy/secrets/` (`api/tokens`, `api/keys`, `alertmanager/alert_webhook_token`, `tls/`) with real values or bind-mount your secret store equivalents.

## 7. CI Integration
1. Configure GitHub Actions to build/push images to GHCR when `main` updates (not included yet).
2. On the VM, run a small script to pull new images and restart: `docker compose pull && docker compose up -d`.

## 8. Monitoring
- Grafana auto-loads datasource/dashboards from `observability/dashboards/gazeqa_overview.json`.
- Prometheus now loads alert rules from `observability/alerts/` and pushes firing alerts to the bundled Alertmanager.
- Alertmanager forwards webhook payloads to the API at `/observability/alerts`; customise `deploy/alertmanager/alertmanager.yml` or add additional receivers for Slack/PagerDuty.
- Adjust `deploy/prometheus/prometheus.yml` targets for your environment (add scrape endpoint for API metrics or file collector).

## 9. Workflow Hooks
Ensure workflow runner posts status and checkpoints to the API endpoints so the SSE stream, Temporal UI, and dashboards stay current (see `docs/run_intake_quickstart.md`).

## 10. Next Steps
- Wire real Temporal workers into `gazeqa/workflow.RunWorkflow`.
- Implement TLS/CORS/secret rotation before exposing the API publicly.
- Deploy Lovable frontend on a separate server pointing to the API load balancer.
- Set `GAZEQA_SIGNING_KEY` (and optional `GAZEQA_SIGNING_TTL`) in deploy/.env so signed artifact downloads work (or supply `GAZEQA_SIGNING_KEY_FILE` for rotation). Never commit real keys.
- If you enable `GAZEQA_ALERT_WEBHOOK_TOKEN`, mount a token file and uncomment the `authorization` block in `deploy/alertmanager/alertmanager.yml` so Alertmanager includes the Bearer token when calling the API.
- Populate Langfuse keys to capture spans once observability is required in the hosted environment.
