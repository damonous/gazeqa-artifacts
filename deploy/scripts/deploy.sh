#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-deploy/docker-compose.yml}
ENV_FILE=${ENV_FILE:-deploy/.env}

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Copy deploy/env.example first." >&2
  exit 1
fi

case "${1:-}" in
  up)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
    ;;
  down)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" down
    ;;
  rebuild)
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build api worker
    ;;
  logs)
    shift || true
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs -f "$@"
    ;;
  *)
    echo "Usage: deploy.sh {up|down|rebuild|logs}" >&2
    exit 1
    ;;
esac
