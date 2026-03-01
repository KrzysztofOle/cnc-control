#!/bin/bash
set -euo pipefail

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

SHADOW_ENABLED="${CNC_SHADOW_ENABLED:-false}"
STATE_FILE="${CNC_SHADOW_STATE_FILE:-/var/lib/cnc-control/shadow_state.json}"
SLOT_FILE="${CNC_ACTIVE_SLOT_FILE:-/var/lib/cnc-control/shadow_active_slot.state}"
MASTER_DIR="${CNC_MASTER_DIR:-/var/lib/cnc-control/master}"
IMG_A="${CNC_USB_IMG_A:-/var/lib/cnc-control/cnc_usb_a.img}"
IMG_B="${CNC_USB_IMG_B:-/var/lib/cnc-control/cnc_usb_b.img}"

get_udc_name() {
    if [ ! -d "/sys/class/udc" ]; then
        return 0
    fi
    ls -A "/sys/class/udc" 2>/dev/null | head -n 1 || true
}

read_shadow_state() {
    if [ ! -f "${STATE_FILE}" ]; then
        echo "?|?|?|"
        return
    fi

    python3 - <<'PY' "${STATE_FILE}"
import json
import sys

state_path = sys.argv[1]
try:
    with open(state_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
except Exception:
    print("?|?|?|")
    raise SystemExit(0)

fsm = str(payload.get("fsm_state", "?") or "?")
active_slot = str(payload.get("active_slot", "?") or "?")
run_id = str(payload.get("run_id", "?") or "?")
last_error = payload.get("last_error")
if isinstance(last_error, dict):
    code = str(last_error.get("code", "") or "")
    message = str(last_error.get("message", "") or "")
else:
    code = ""
    message = ""

print(f"{fsm}|{active_slot}|{run_id}|{code}|{message}")
PY
}

resolve_runtime_lun() {
    local configfs_file="/sys/kernel/config/usb_gadget/g1/functions/mass_storage.usb0/lun.0/file"
    local module_file="/sys/module/g_mass_storage/parameters/file"

    if [ -r "${configfs_file}" ]; then
        tr -d '\r\n' < "${configfs_file}"
        return 0
    fi

    if [ -r "${module_file}" ]; then
        tr -d '\r\n' < "${module_file}"
        return 0
    fi

    return 1
}

STATE_PAYLOAD="$(read_shadow_state)"
IFS='|' read -r FSM_STATE ACTIVE_SLOT RUN_ID LAST_ERROR_CODE LAST_ERROR_MESSAGE <<< "${STATE_PAYLOAD}"

if [ "${ACTIVE_SLOT}" = "?" ] && [ -f "${SLOT_FILE}" ]; then
    ACTIVE_SLOT="$(tr -d '\r\n\t ' < "${SLOT_FILE}" | tr '[:lower:]' '[:upper:]')"
fi

EXPECTED_IMAGE="?"
case "${ACTIVE_SLOT}" in
    A)
        EXPECTED_IMAGE="${IMG_A}"
        ;;
    B)
        EXPECTED_IMAGE="${IMG_B}"
        ;;
esac

UDC_NAME="$(get_udc_name)"
RUNTIME_LUN="$(resolve_runtime_lun 2>/dev/null || true)"

if lsmod | grep -q '^g_mass_storage' && [ -n "${UDC_NAME}" ]; then
    EXPORT_STATUS="AKTYWNY"
elif lsmod | grep -q '^g_mass_storage'; then
    EXPORT_STATUS="NIEAKTYWNY (BRAK UDC)"
else
    EXPORT_STATUS="NIEAKTYWNY"
fi

RUNTIME_MATCH="NIEZNANA"
if [ -n "${RUNTIME_LUN}" ] && [ "${EXPECTED_IMAGE}" != "?" ]; then
    if [ "${RUNTIME_LUN}" = "${EXPECTED_IMAGE}" ]; then
        RUNTIME_MATCH="TAK"
    else
        RUNTIME_MATCH="NIE"
    fi
fi

echo "=============================="
echo " CNC SHADOW STATUS"
echo "=============================="
echo "Tryb pracy: SHADOW (A/B)"
echo "SHADOW enabled: ${SHADOW_ENABLED}"
echo "FSM: ${FSM_STATE}"
echo "ACTIVE_SLOT: ${ACTIVE_SLOT}"
echo "RUN_ID: ${RUN_ID}"
echo "Master dir: ${MASTER_DIR}"
echo "UDC: ${UDC_NAME:-BRAK}"
echo "Eksport USB: ${EXPORT_STATUS}"
echo "Runtime LUN: ${RUNTIME_LUN:-BRAK}"
echo "Oczekiwany obraz: ${EXPECTED_IMAGE}"
echo "Runtime zgodny z ACTIVE_SLOT: ${RUNTIME_MATCH}"

if [ -n "${LAST_ERROR_CODE}" ] || [ -n "${LAST_ERROR_MESSAGE}" ]; then
    echo "SHADOW ERROR: ${LAST_ERROR_CODE:-ERR} - ${LAST_ERROR_MESSAGE:-Brak szczegolow}"
fi

echo ""
echo "Pliki CNC (master):"
if [ -d "${MASTER_DIR}" ]; then
    ls -lh "${MASTER_DIR}" | sed -n '1,20p'
else
    echo "Brak katalogu: ${MASTER_DIR}"
fi

echo ""
echo "=============================="
