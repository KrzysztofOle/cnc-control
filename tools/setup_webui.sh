#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "${PYTHON_BIN}" ]; then
    echo "Brak python3 w PATH."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

SERVICE_NAME="cnc-webui.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
RUN_AS_USER="${SUDO_USER:-$USER}"

SERVICE_CONTENT="[Unit]
Description=CNC Control Web UI
After=network.target local-fs.target

[Service]
Type=simple
User=${RUN_AS_USER}
WorkingDirectory=${REPO_ROOT}
ExecStart=${PYTHON_BIN} -u ${REPO_ROOT}/webui/app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
"

if [ "${EUID}" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Brak uprawnien do zapisu w /etc i brak sudo."
        exit 1
    fi
    echo "${SERVICE_CONTENT}" | sudo tee "${SERVICE_PATH}" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    sudo systemctl restart "${SERVICE_NAME}"
else
    echo "${SERVICE_CONTENT}" > "${SERVICE_PATH}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}"
    systemctl restart "${SERVICE_NAME}"
fi

echo "Gotowe. Status: systemctl status ${SERVICE_NAME}"
