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
USB_SCRIPT="${REPO_ROOT}/usb_mode.sh"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

if [ ! -f "${USB_SCRIPT}" ]; then
    echo "Brak pliku: ${USB_SCRIPT}"
    exit 1
fi

SERVICE_NAME="cnc-usb.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

SERVICE_CONTENT="[Unit]
Description=CNC USB Mode (RichAuto)
After=multi-user.target network.target

[Service]
Type=oneshot
ExecStart=${USB_SCRIPT}
RemainAfterExit=yes

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
