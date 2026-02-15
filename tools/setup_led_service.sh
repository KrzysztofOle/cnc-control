#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT_DEFAULT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT_INPUT="${1:-${REPO_ROOT_DEFAULT}}"
if [ "$(basename "${REPO_ROOT_INPUT}")" = "tools" ]; then
    REPO_ROOT_INPUT="$(cd "${REPO_ROOT_INPUT}/.." && pwd)"
fi
if command -v readlink >/dev/null 2>&1; then
    REPO_ROOT="$(readlink -f "${REPO_ROOT_INPUT}")"
else
    REPO_ROOT="${REPO_ROOT_INPUT}"
fi

LED_APP="${REPO_ROOT}/led_status.py"

PYTHON_BIN="$(command -v python || true)"
if [ -z "${PYTHON_BIN}" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "${PYTHON_BIN}" ]; then
    echo "Brak python/python3 w PATH."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

if [ ! -f "${LED_APP}" ]; then
    echo "Brak pliku: ${LED_APP}"
    exit 1
fi

SERVICE_NAME="cnc-led.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

SERVICE_CONTENT="[Unit]
Description=CNC LED Status Service
After=network.target
Wants=network.target

[Service]
Type=simple
EnvironmentFile=/etc/cnc-control/cnc-control.env
WorkingDirectory=${REPO_ROOT}
ExecStart=${PYTHON_BIN} led_status.py
Restart=always
RestartSec=2

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
