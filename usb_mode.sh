#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}" && pwd)"
IMG="${CNC_USB_IMG:-${REPO_ROOT}/usb/cnc_usb.img}"
MOUNT="${CNC_USB_MOUNT:-/mnt/cnc_usb}"

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
