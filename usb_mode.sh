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

get_udc_name() {
    if [ ! -d "/sys/class/udc" ]; then
        return 0
    fi
    ls -A "/sys/class/udc" 2>/dev/null | head -n 1 || true
}

ensure_udc_available() {
    local udc_name=""
    local cfg_line=""
    local cmdline_file=""

    udc_name="$(get_udc_name)"
    if [ -n "${udc_name}" ]; then
        echo "Wykryto UDC: ${udc_name}"
        return 0
    fi

    # PL: Proba naprawy bez restartu - przeladowanie dwc2 w trybie peripheral.
    # EN: Recovery attempt without reboot - reload dwc2 in peripheral mode.
    echo "Brak UDC. Proba przeladowania dwc2 (peripheral)..."
    if lsmod | grep -q '^g_mass_storage'; then
        sudo modprobe -r g_mass_storage || true
    fi
    if lsmod | grep -q '^dwc2'; then
        sudo modprobe -r dwc2 || true
    fi

    if ! sudo modprobe dwc2 dr_mode=peripheral 2>/dev/null; then
        sudo modprobe dwc2
    fi
    sleep 1

    udc_name="$(get_udc_name)"
    if [ -n "${udc_name}" ]; then
        echo "Wykryto UDC po przeladowaniu: ${udc_name}"
        return 0
    fi

    echo "Brak dostepnego UDC (/sys/class/udc puste)."
    cfg_line="$(grep -h -E '^[[:space:]]*dtoverlay=dwc2' /boot/firmware/config.txt /boot/config.txt 2>/dev/null | tail -n 1 || true)"
    if [ -n "${cfg_line}" ]; then
        echo "Aktualny wpis dtoverlay: ${cfg_line}"
    fi
    cmdline_file=""
    if [ -f "/boot/firmware/cmdline.txt" ]; then
        cmdline_file="/boot/firmware/cmdline.txt"
    elif [ -f "/boot/cmdline.txt" ]; then
        cmdline_file="/boot/cmdline.txt"
    fi
    if [ -n "${cmdline_file}" ]; then
        echo "cmdline (${cmdline_file}): $(cat "${cmdline_file}")"
    fi
    echo "Sprawdz: dtoverlay=dwc2,dr_mode=peripheral oraz kabel DATA w porcie USB (nie PWR IN)."
    return 1
}

ensure_usb_image() {
    local size_mb="${CNC_USB_IMG_SIZE_MB:-1024}"
    local usb_label="${CNC_USB_LABEL:-CNC_USB}"

    if [ -e "${IMG}" ] && [ ! -f "${IMG}" ]; then
        echo "Sciezka CNC_USB_IMG nie wskazuje na zwykly plik: ${IMG}"
        return 1
    fi

    if [ -f "${IMG}" ] && [ -s "${IMG}" ]; then
        return 0
    fi

    if ! [[ "${size_mb}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Nieprawidlowa wartosc CNC_USB_IMG_SIZE_MB: ${size_mb}"
        return 1
    fi

    if [ -z "${usb_label}" ]; then
        echo "Nieprawidlowa wartosc CNC_USB_LABEL: pusty label."
        return 1
    fi

    if [ "${#usb_label}" -gt 11 ]; then
        echo "Nieprawidlowa wartosc CNC_USB_LABEL: maksymalnie 11 znakow dla FAT."
        return 1
    fi

    if ! command -v mkfs.vfat >/dev/null 2>&1; then
        echo "Brak mkfs.vfat. Zainstaluj pakiet dosfstools."
        return 1
    fi

    local image_dir
    image_dir="$(dirname "${IMG}")"
    echo "Tworzenie obrazu USB (${size_mb}MB, label=${usb_label}): ${IMG}"
    sudo mkdir -p "${image_dir}"
    sudo truncate -s "${size_mb}M" "${IMG}"
    sudo mkfs.vfat -F 32 -n "${usb_label}" "${IMG}" >/dev/null
    sudo chmod 664 "${IMG}"
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

set_led_mode USB

echo "[USB MODE] Przełączanie na tryb CNC (USB)..."

if ! ensure_usb_image; then
    echo "Brak obrazu USB: ${IMG}"
    exit 1
fi

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

if ! ensure_udc_available; then
    exit 1
fi

# Podłącz gadget w trybie RO
echo "Podłączanie USB Mass Storage (RO)..."
sudo modprobe g_mass_storage file="${IMG}" removable=1 ro=1

set_led_mode USB

echo "[USB MODE] Gotowe. RichAuto może korzystać z USB."
