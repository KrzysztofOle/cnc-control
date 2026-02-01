#!/bin/bash
set -e

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

echo "[NET MODE] Gotowe. Możesz kopiować pliki przez sieć."
