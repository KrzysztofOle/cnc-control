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

# Podłącz gadget w trybie RO
echo "Podłączanie USB Mass Storage (RO)..."
sudo modprobe g_mass_storage file="${IMG}" removable=1 ro=1

echo "[USB MODE] Gotowe. RichAuto może korzystać z USB."
