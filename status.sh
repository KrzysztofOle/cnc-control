#!/bin/bash

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

echo "=============================="
echo " CNC USB STATUS"
echo "=============================="

# Sprawdzenie trybu
UDC_NAME="$(get_udc_name)"
if lsmod | grep -q g_mass_storage && [ -n "${UDC_NAME}" ]; then
    MODE="USB (CNC)"
elif lsmod | grep -q g_mass_storage; then
    MODE="USB (NIEAKTYWNY - BRAK UDC)"
else
    MODE="SIEĆ (UPLOAD)"
fi

echo "Tryb pracy: $MODE"
echo "Punkt montowania: $MOUNT"
if [ -n "${UDC_NAME}" ]; then
    echo "UDC: ${UDC_NAME}"
else
    echo "UDC: BRAK"
fi

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
