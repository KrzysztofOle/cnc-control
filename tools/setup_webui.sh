#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT_DEFAULT="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT_INPUT="${1:-${REPO_ROOT_DEFAULT}}"
if [ "$(basename "${REPO_ROOT_INPUT}")" = "webui" ]; then
    REPO_ROOT_INPUT="$(cd "${REPO_ROOT_INPUT}/.." && pwd)"
fi
if command -v readlink >/dev/null 2>&1; then
    REPO_ROOT="$(readlink -f "${REPO_ROOT_INPUT}")"
else
    REPO_ROOT="${REPO_ROOT_INPUT}"
fi
WEBUI_DIR="${REPO_ROOT}/webui"
WEBUI_APP="${WEBUI_DIR}/app.py"

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "${PYTHON_BIN}" ]; then
    echo "Brak python3 w PATH."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

if [ ! -f "${WEBUI_APP}" ]; then
    echo "Brak pliku: ${WEBUI_APP}"
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
WorkingDirectory=${WEBUI_DIR}
ExecStart=${PYTHON_BIN} -u ${WEBUI_APP}
Restart=on-failure
RestartSec=3

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
echo "Uwaga: jesli repozytorium zostalo przeniesione, uruchom skrypt ponownie z nowa sciezka."
