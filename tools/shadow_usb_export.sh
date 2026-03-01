#!/bin/bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
    RESOLVED_PATH="$(readlink -f "${SCRIPT_PATH}" 2>/dev/null || true)"
    if [ -n "${RESOLVED_PATH}" ]; then
        SCRIPT_PATH="${RESOLVED_PATH}"
    fi
fi
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${CNC_VENV_DIR:-${REPO_ROOT}/.venv}"
VENV_PYTHON="${VENV_DIR}/bin/python3"

ENV_FILE="/etc/cnc-control/cnc-control.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "Brak pliku konfiguracji: ${ENV_FILE}"
    exit 1
fi

# PL: Zaladuj konfiguracje runtime projektu.
# EN: Load project runtime configuration.
set -a
# shellcheck source=/etc/cnc-control/cnc-control.env
source "${ENV_FILE}"
set +a

if [ "${CNC_SHADOW_ENABLED:-false}" != "true" ]; then
    echo "Tryb SHADOW jest wylaczony (CNC_SHADOW_ENABLED!=true)."
    exit 1
fi

SLOT_FILE="${CNC_ACTIVE_SLOT_FILE:-/var/lib/cnc-control/shadow_active_slot.state}"
IMG_A="${CNC_USB_IMG_A:-/var/lib/cnc-control/cnc_usb_a.img}"
IMG_B="${CNC_USB_IMG_B:-/var/lib/cnc-control/cnc_usb_b.img}"

if [ ! -f "${SLOT_FILE}" ]; then
    echo "Brak pliku aktywnego slotu: ${SLOT_FILE}"
    exit 1
fi

ACTIVE_SLOT="$(tr -d '\r\n' < "${SLOT_FILE}" | tr '[:lower:]' '[:upper:]')"
case "${ACTIVE_SLOT}" in
    A)
        ACTIVE_IMAGE="${IMG_A}"
        ;;
    B)
        ACTIVE_IMAGE="${IMG_B}"
        ;;
    *)
        echo "Nieprawidlowa wartosc ACTIVE_SLOT: ${ACTIVE_SLOT}"
        exit 1
        ;;
esac

if [ ! -f "${ACTIVE_IMAGE}" ] || [ ! -s "${ACTIVE_IMAGE}" ]; then
    echo "Brak poprawnego obrazu aktywnego slotu: ${ACTIVE_IMAGE}"
    exit 1
fi

get_udc_name() {
    if [ ! -d "/sys/class/udc" ]; then
        return 0
    fi
    ls -A "/sys/class/udc" 2>/dev/null | head -n 1 || true
}

ensure_udc_available() {
    local udc_name=""
    udc_name="$(get_udc_name)"
    if [ -n "${udc_name}" ]; then
        echo "Wykryto UDC: ${udc_name}"
        return 0
    fi

    if ! lsmod | grep -q '^dwc2'; then
        sudo modprobe dwc2 || true
    fi
    sleep 1
    udc_name="$(get_udc_name)"
    if [ -n "${udc_name}" ]; then
        echo "Wykryto UDC po przeladowaniu: ${udc_name}"
        return 0
    fi

    echo "Brak dostepnego UDC (/sys/class/udc puste)."
    return 1
}

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

echo "[SHADOW EXPORT] Start eksportu USB dla aktywnego slotu ${ACTIVE_SLOT} (${ACTIVE_IMAGE})..."

if lsmod | grep -q '^g_mass_storage'; then
    echo "Odłączanie poprzedniego eksportu USB..."
    sudo modprobe -r g_mass_storage
fi

if ! ensure_udc_available; then
    exit 1
fi

echo "Podłączanie USB Mass Storage (RO) dla SHADOW..."
sudo modprobe g_mass_storage file="${ACTIVE_IMAGE}" removable=1 ro=1
set_led_mode SHADOW_READY

echo "[SHADOW EXPORT] Gotowe."
