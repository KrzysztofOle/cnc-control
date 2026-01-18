#!/bin/bash

IMG="/home/andrzej/usb/cnc_usb.img"
MOUNT="/mnt/cnc_usb"

echo "=============================="
echo " CNC USB STATUS"
echo "=============================="

# Sprawdzenie trybu
if lsmod | grep -q g_mass_storage; then
    MODE="USB (CNC)"
else
    MODE="SIEĆ (UPLOAD)"
fi

echo "Tryb pracy: $MODE"

# Sprawdzenie montowania
if mount | grep -q "$IMG"; then
    echo "Obraz FAT: ZAMONTOWANY (RW)"
else
    echo "Obraz FAT: NIEZAMONTOWANY"
fi

# Konflikt bezpieczeństwa
if lsmod | grep -q g_mass_storage && mount | grep -q "$IMG"; then
    echo "!!! UWAGA: KONFLIKT (USB + RW jednocześnie) !!!"
fi

# Lista plików
echo ""
echo "Pliki CNC:"

if [ "$MODE" = "SIEĆ (UPLOAD)" ] && [ -d "$MOUNT" ]; then
    ls -lh "$MOUNT"
else
    echo "(niedostępne w trybie USB)"
fi

echo ""
echo "=============================="
