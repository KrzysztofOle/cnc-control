#!/bin/bash
set -e

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
    RESOLVED_PATH="$(readlink -f "${SCRIPT_PATH}" 2>/dev/null || true)"
    if [ -n "${RESOLVED_PATH}" ]; then
        SCRIPT_PATH="${RESOLVED_PATH}"
    fi
fi
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
VENV_DIR="${CNC_VENV_DIR:-${REPO_ROOT}/.venv}"
VENV_PYTHON="${VENV_DIR}/bin/python3"

ENV_FILE="/etc/cnc-control/cnc-control.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "Brak pliku konfiguracji: ${ENV_FILE}"
    exit 1
fi

# shellcheck source=/etc/cnc-control/cnc-control.env
set -a
source "${ENV_FILE}"
set +a

if [ -z "${CNC_MOUNT_POINT:-}" ]; then
    if [ -n "${CNC_USB_MOUNT:-}" ]; then
        CNC_MOUNT_POINT="${CNC_USB_MOUNT}"
    elif [ -n "${CNC_UPLOAD_DIR:-}" ]; then
        CNC_MOUNT_POINT="${CNC_UPLOAD_DIR}"
    fi
fi

if [ -z "${CNC_USB_IMG:-}" ]; then
    echo "Brak zmiennej CNC_USB_IMG w konfiguracji."
    exit 1
fi

if [ -z "${CNC_MOUNT_POINT:-}" ]; then
    echo "Brak zmiennej CNC_MOUNT_POINT w konfiguracji."
    exit 1
fi

IMG="${CNC_USB_IMG}"
MOUNT="${CNC_MOUNT_POINT}"

set_led_mode() {
    local mode="${1}"

    if [ -x "${VENV_PYTHON}" ]; then
        if "${VENV_PYTHON}" "${REPO_ROOT}/led_status_cli.py" "${mode}" >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v python3 >/dev/null 2>&1; then
        if python3 "${REPO_ROOT}/led_status_cli.py" "${mode}" >/dev/null 2>&1; then
            return 0
        fi
    fi

    echo "[WARN] Nie mozna ustawic trybu LED: ${mode}" >&2
    return 0
}

set_led_mode UPLOAD

echo "[NET MODE] Przełączanie na tryb sieciowy (upload)..."

# Odłącz USB gadget
if lsmod | grep -q g_mass_storage; then
    echo "Odłączanie USB gadget..."
    sudo modprobe -r g_mass_storage
fi

# Zamontuj obraz lokalnie
if ! mountpoint -q "${MOUNT}"; then
    echo "Montowanie obrazu FAT..."
    sudo mount -o loop,rw,uid=1000,gid=1000,fmask=0022,dmask=0022 "${IMG}" "${MOUNT}"
fi

set_led_mode UPLOAD

echo "[NET MODE] Gotowe. Możesz kopiować pliki przez sieć."
