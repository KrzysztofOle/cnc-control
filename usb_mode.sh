#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

set_led_mode USB

echo "[USB MODE] Przełączanie na tryb CNC (USB)..."

# Odmontuj obraz jeśli jest zamontowany
if mountpoint -q "${MOUNT}"; then
    echo "Odmontowywanie obrazu..."
    sudo umount "${MOUNT}"
fi

# Odłącz gadget jeśli był załadowany
if lsmod | grep -q g_mass_storage; then
    echo "Odłączanie USB gadget..."
    sudo modprobe -r g_mass_storage
fi

# PL: Upewnij sie, ze sterownik OTG (dwc2) jest ladowany dynamicznie.
# EN: Ensure the OTG (dwc2) driver is loaded dynamically.
if ! lsmod | grep -q '^dwc2'; then
    echo "Ladowanie sterownika dwc2..."
    sudo modprobe dwc2
fi

# Podłącz gadget w trybie RO
echo "Podłączanie USB Mass Storage (RO)..."
sudo modprobe g_mass_storage file="${IMG}" removable=1 ro=1

set_led_mode USB

echo "[USB MODE] Gotowe. RichAuto może korzystać z USB."
