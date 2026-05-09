#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="mhxii-keepalive"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
ENV_FILE="/etc/${SERVICE_NAME}.env"

if [[ -z "${MHXII_SERVICE_URL:-}" ]]; then
  echo "Set MHXII_SERVICE_URL before running this script."
  echo "Example: export MHXII_SERVICE_URL=https://your-service.onrender.com"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${REPO_DIR}/keepalive.py" ]]; then
  echo "keepalive.py not found at ${REPO_DIR}/keepalive.py"
  exit 1
fi

sudo tee "${ENV_FILE}" >/dev/null <<EOF
KEEPALIVE_URL=${MHXII_SERVICE_URL}
KEEPALIVE_INTERVAL=${KEEPALIVE_INTERVAL:-240}
EOF

sed "s|__REPO_DIR__|${REPO_DIR}|g" "${SCRIPT_DIR}/mhxii-keepalive.service" | sudo tee "${SERVICE_FILE}" >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"
sudo systemctl status "${SERVICE_NAME}.service" --no-pager
