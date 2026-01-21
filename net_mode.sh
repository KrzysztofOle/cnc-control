#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}" && pwd)"
IMG="${CNC_USB_IMG:-${REPO_ROOT}/usb/cnc_usb.img}"
MOUNT="${CNC_USB_MOUNT:-/mnt/cnc_usb}"

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
