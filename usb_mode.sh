#!/bin/bash
set -e

echo "[USB MODE] Przełączanie na tryb CNC (USB)..."

# Odmontuj obraz jeśli jest zamontowany
if mountpoint -q /mnt/cnc_usb; then
    echo "Odmontowywanie obrazu..."
    sudo umount /mnt/cnc_usb
fi

# Odłącz gadget jeśli był załadowany
if lsmod | grep -q g_mass_storage; then
    echo "Odłączanie USB gadget..."
    sudo modprobe -r g_mass_storage
fi

# Podłącz gadget w trybie RO
echo "Podłączanie USB Mass Storage (RO)..."
sudo modprobe g_mass_storage file=/home/andrzej/usb/cnc_usb.img removable=1 ro=1

echo "[USB MODE] Gotowe. RichAuto może korzystać z USB."

