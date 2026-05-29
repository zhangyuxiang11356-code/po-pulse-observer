#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
ENV_FILE="${SCRIPT_DIR}/.env"
PROJECT_NAME="trendradar"
BUILD_CONTEXT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOCKERFILE="${SCRIPT_DIR}/Dockerfile"
IMAGE_NAME="trendradar-local:latest"

compose() {
  podman compose -p "${PROJECT_NAME}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

build_image() {
  podman build -f "${DOCKERFILE}" -t "${IMAGE_NAME}" "${BUILD_CONTEXT}"
}

help_text() {
  cat <<'EOF'
TrendRadar Podman helper

Usage:
  ./podman.sh up
  ./podman.sh down
  ./podman.sh logs
  ./podman.sh status
  ./podman.sh exec "python manage.py status"
  ./podman.sh mcp-up
EOF
}

if ! command -v podman >/dev/null 2>&1; then
  echo "podman 命令当前不可用，请先确认 Podman 已安装并加入 PATH。" >&2
  exit 1
fi

action="${1:-help}"
shift || true

case "${action}" in
  up)
    build_image
    compose up -d trendradar
    ;;
  down)
    compose down
    ;;
  logs)
    podman logs -f trendradar
    ;;
  status)
    podman ps --filter name=trendradar
    ;;
  exec)
    if [[ $# -eq 0 ]]; then
      echo '请提供容器内命令，例如: ./podman.sh exec "python manage.py status"' >&2
      exit 1
    fi
    podman exec -it trendradar sh -lc "$*"
    ;;
  mcp-up)
    compose up -d trendradar-mcp
    ;;
  *)
    help_text
    ;;
esac
