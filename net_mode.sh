#!/bin/bash
set -e

echo "[NET MODE] Przełączanie na tryb sieciowy (upload)..."

# Odłącz USB gadget
if lsmod | grep -q g_mass_storage; then
    echo "Odłączanie USB gadget..."
    sudo modprobe -r g_mass_storage
fi

# Zamontuj obraz lokalnie
if ! mountpoint -q /mnt/cnc_usb; then
    echo "Montowanie obrazu FAT..."
    sudo mount -o loop,rw,uid=1000,gid=1000,fmask=0022,dmask=0022 /home/andrzej/usb/cnc_usb.img /mnt/cnc_usb
fi

echo "[NET MODE] Gotowe. Możesz kopiować pliki przez sieć."

