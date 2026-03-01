#!/usr/bin/env bash
set -u
set -o pipefail

JSON_MODE=false
STRICT_MODE=false
ENV_FILE="/etc/cnc-control/cnc-control.env"

REQUIRED_PACKAGES=(
    dosfstools
    mtools
    util-linux
    kmod
    inotify-tools
)

REQUIRED_ENV_VARS=(
    CNC_SHADOW_ENABLED
    CNC_MASTER_DIR
    CNC_USB_IMG_A
    CNC_USB_IMG_B
    CNC_ACTIVE_SLOT_FILE
    CNC_SHADOW_STATE_FILE
    CNC_SHADOW_HISTORY_FILE
    CNC_SHADOW_SLOT_SIZE_MB
    CNC_SHADOW_TMP_SUFFIX
    CNC_SHADOW_LOCK_FILE
    CNC_SHADOW_CONFIG_VERSION
    CNC_CONTROL_REPO
)

REQUIRED_UNITS=(
    cnc-webui.service
    cnc-usb.service
    cnc-led.service
)

usage() {
    cat <<'EOF'
Uzycie: tools/cnc_install_validation.sh [--json] [--strict]

Tryby:
  domyslny  - raport tekstowy
  --json    - raport JSON
  --strict  - FAIL, jesli wystapi WARN

Exit codes:
  0 - PASS
  1 - FAIL
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --json)
            JSON_MODE=true
            ;;
        --strict)
            STRICT_MODE=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Nieznany argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

SCRIPT_PATH="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
    RESOLVED_PATH="$(readlink -f "${SCRIPT_PATH}" 2>/dev/null || true)"
    if [ -n "${RESOLVED_PATH}" ]; then
        SCRIPT_PATH="${RESOLVED_PATH}"
    fi
fi
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

CHECK_FILE="$(mktemp)"
trap 'rm -f "${CHECK_FILE}"' EXIT

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

sanitize_text() {
    printf '%s' "$1" | tr '\n\r\t' '   '
}

record_check() {
    local status="$1"
    local name="$2"
    local detail
    detail="$(sanitize_text "$3")"

    printf '%s\t%s\t%s\n' "${status}" "${name}" "${detail}" >> "${CHECK_FILE}"
    case "${status}" in
        PASS) PASS_COUNT=$((PASS_COUNT + 1)) ;;
        WARN) WARN_COUNT=$((WARN_COUNT + 1)) ;;
        FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
        *)
            WARN_COUNT=$((WARN_COUNT + 1))
            printf 'WARN\t%s\t%s\n' "${name}" "Nieznany status: ${status}" >> "${CHECK_FILE}"
            ;;
    esac
}

parse_env_ok=true
if [ -f "${ENV_FILE}" ]; then
    set -a
    if ! source "${ENV_FILE}"; then
        parse_env_ok=false
        record_check "FAIL" "Plik env" "Nie mozna sparsowac: ${ENV_FILE}"
    else
        record_check "PASS" "Plik env" "Znaleziono i zaladowano: ${ENV_FILE}"
    fi
    set +a
else
    parse_env_ok=false
    record_check "FAIL" "Plik env" "Brak pliku: ${ENV_FILE}"
fi

CNC_CONTROL_REPO_VALUE="${CNC_CONTROL_REPO:-${REPO_ROOT}}"
VENV_DIR="${CNC_VENV_DIR:-${CNC_CONTROL_REPO_VALUE}/.venv}"
TARGET_MARKER="${VENV_DIR}/.cnc_target"
IMG_A="${CNC_USB_IMG_A:-/var/lib/cnc-control/cnc_usb_a.img}"
IMG_B="${CNC_USB_IMG_B:-/var/lib/cnc-control/cnc_usb_b.img}"
ACTIVE_SLOT_FILE="${CNC_ACTIVE_SLOT_FILE:-/var/lib/cnc-control/shadow_active_slot.state}"
STATE_FILE="${CNC_SHADOW_STATE_FILE:-/var/lib/cnc-control/shadow_state.json}"
TMP_SUFFIX="${CNC_SHADOW_TMP_SUFFIX:-.tmp}"

if command -v dpkg-query >/dev/null 2>&1; then
    for pkg in "${REQUIRED_PACKAGES[@]}"; do
        pkg_state="$(dpkg-query -W -f='${Status}' "${pkg}" 2>/dev/null || true)"
        if [ "${pkg_state}" = "install ok installed" ]; then
            record_check "PASS" "Pakiet ${pkg}" "Zainstalowany"
        else
            record_check "FAIL" "Pakiet ${pkg}" "Brak pakietu"
        fi
    done
else
    record_check "FAIL" "Pakiety SHADOW" "Brak dpkg-query; nie mozna zweryfikowac pakietow"
fi

if [ -d "${CNC_CONTROL_REPO_VALUE}" ]; then
    record_check "PASS" "Repozytorium" "Istnieje: ${CNC_CONTROL_REPO_VALUE}"
else
    record_check "FAIL" "Repozytorium" "Brak katalogu: ${CNC_CONTROL_REPO_VALUE}"
fi

if [ -d "${CNC_CONTROL_REPO_VALUE}/.git" ]; then
    record_check "PASS" "Repozytorium git" "Znaleziono .git"
else
    record_check "FAIL" "Repozytorium git" "Brak ${CNC_CONTROL_REPO_VALUE}/.git"
fi

if [ -d "${VENV_DIR}" ]; then
    record_check "PASS" ".venv" "Istnieje: ${VENV_DIR}"
else
    record_check "FAIL" ".venv" "Brak katalogu: ${VENV_DIR}"
fi

if [ -x "${VENV_DIR}/bin/python3" ] || [ -x "${VENV_DIR}/bin/python" ]; then
    record_check "PASS" "Python w .venv" "Interpreter znaleziony"
else
    record_check "FAIL" "Python w .venv" "Brak interpretera w ${VENV_DIR}/bin"
fi

if [ -f "${TARGET_MARKER}" ]; then
    record_check "PASS" "Marker targetu (.cnc_target) istnieje" "${TARGET_MARKER}"
    marker_value="$(tr -d '\r\n\t ' < "${TARGET_MARKER}" | tr '[:upper:]' '[:lower:]')"
    if [ "${marker_value}" = "rpi" ]; then
        record_check "PASS" "Marker targetu (.cnc_target)=rpi" "${TARGET_MARKER}=rpi"
    else
        record_check "FAIL" "Marker targetu (.cnc_target)=rpi" "${TARGET_MARKER}=${marker_value:-<pusty>}, oczekiwano rpi"
    fi
else
    record_check "FAIL" "Marker targetu (.cnc_target) istnieje" "Brak pliku: ${TARGET_MARKER}"
    record_check "FAIL" "Marker targetu (.cnc_target)=rpi" "Brak pliku: ${TARGET_MARKER}"
fi

if [ "${parse_env_ok}" = true ]; then
    for key in "${REQUIRED_ENV_VARS[@]}"; do
        value="${!key-}"
        if [ -n "${value}" ]; then
            record_check "PASS" "Zmienna ${key}" "Ustawiona"
        else
            record_check "FAIL" "Zmienna ${key}" "Brak lub pusta"
        fi
    done
else
    for key in "${REQUIRED_ENV_VARS[@]}"; do
        record_check "FAIL" "Zmienna ${key}" "Pominieto: env niezaladowany"
    done
fi

if [ "${CNC_SHADOW_ENABLED:-}" = "true" ]; then
    record_check "PASS" "Tryb SHADOW-only" "CNC_SHADOW_ENABLED=true"
else
    record_check "FAIL" "Tryb SHADOW-only" "CNC_SHADOW_ENABLED=${CNC_SHADOW_ENABLED:-<brak>}, oczekiwano true"
fi

if [ -f "${IMG_A}" ] && [ -s "${IMG_A}" ]; then
    record_check "PASS" "Slot A" "OK: ${IMG_A}"
else
    record_check "FAIL" "Slot A" "Brak lub pusty plik: ${IMG_A}"
fi

if [ -f "${IMG_B}" ] && [ -s "${IMG_B}" ]; then
    record_check "PASS" "Slot B" "OK: ${IMG_B}"
else
    record_check "FAIL" "Slot B" "Brak lub pusty plik: ${IMG_B}"
fi

ACTIVE_SLOT=""
if [ -f "${ACTIVE_SLOT_FILE}" ]; then
    ACTIVE_SLOT="$(tr -d '\r\n\t ' < "${ACTIVE_SLOT_FILE}" | tr '[:lower:]' '[:upper:]')"
    case "${ACTIVE_SLOT}" in
        A|B)
            record_check "PASS" "ACTIVE_SLOT_FILE" "${ACTIVE_SLOT_FILE}: ${ACTIVE_SLOT}"
            ;;
        *)
            record_check "FAIL" "ACTIVE_SLOT_FILE" "${ACTIVE_SLOT_FILE}: niepoprawna wartosc '${ACTIVE_SLOT}'"
            ;;
    esac
else
    record_check "FAIL" "ACTIVE_SLOT_FILE" "Brak pliku: ${ACTIVE_SLOT_FILE}"
fi

if [ -f "${STATE_FILE}" ]; then
    if command -v python3 >/dev/null 2>&1; then
        state_validation="$(python3 - "${STATE_FILE}" <<'PY'
import json
import sys
from pathlib import Path

ALLOWED_STATES = {
    "IDLE",
    "CHANGE_DETECTED",
    "BUILD_SLOT_A",
    "BUILD_SLOT_B",
    "EXPORT_STOP",
    "EXPORT_START",
    "READY",
    "ERROR",
}

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(payload, dict):
    raise ValueError("root is not an object")

required = ("fsm_state", "active_slot", "rebuild_slot", "run_id", "rebuild_counter")
missing = [key for key in required if key not in payload]
if missing:
    raise ValueError("missing keys: " + ", ".join(missing))

fsm_state = str(payload["fsm_state"])
if fsm_state not in ALLOWED_STATES:
    raise ValueError(f"invalid fsm_state: {fsm_state}")

active_slot = str(payload["active_slot"]).upper()
if active_slot not in {"A", "B"}:
    raise ValueError(f"invalid active_slot: {active_slot}")

rebuild_slot = payload["rebuild_slot"]
if rebuild_slot not in {"A", "B", None}:
    raise ValueError(f"invalid rebuild_slot: {rebuild_slot}")

run_id = int(payload["run_id"])
rebuild_counter = int(payload["rebuild_counter"])
if run_id != rebuild_counter:
    raise ValueError("rebuild_counter must equal run_id")

print(f"fsm_state={fsm_state}; active_slot={active_slot}; run_id={run_id}")
PY
        )"
        state_rc=$?
        if [ "${state_rc}" -eq 0 ]; then
            record_check "PASS" "CNC_SHADOW_STATE_FILE JSON" "${state_validation}"
        else
            record_check "FAIL" "CNC_SHADOW_STATE_FILE JSON" "${state_validation}"
        fi
    else
        record_check "FAIL" "CNC_SHADOW_STATE_FILE JSON" "Brak python3 do walidacji JSON"
    fi
else
    record_check "FAIL" "CNC_SHADOW_STATE_FILE" "Brak pliku: ${STATE_FILE}"
fi

tmp_files=()
for tmp_path in "${IMG_A}${TMP_SUFFIX}" "${IMG_B}${TMP_SUFFIX}"; do
    if [ -e "${tmp_path}" ]; then
        tmp_files+=("${tmp_path}")
    fi
done

while IFS= read -r dir_path; do
    [ -d "${dir_path}" ] || continue
    while IFS= read -r file_path; do
        [ -n "${file_path}" ] || continue
        tmp_files+=("${file_path}")
    done < <(find "${dir_path}" -maxdepth 1 -type f -name '*.tmp' 2>/dev/null | sort)
done < <(printf '%s\n' "$(dirname "${IMG_A}")" "$(dirname "${IMG_B}")" "$(dirname "${STATE_FILE}")" "$(dirname "${ACTIVE_SLOT_FILE}")" | awk 'NF' | sort -u)

if [ "${#tmp_files[@]}" -gt 0 ]; then
    uniq_tmp="$(printf '%s\n' "${tmp_files[@]}" | awk 'NF' | sort -u | tr '\n' '; ')"
    record_check "FAIL" "Pliki .tmp" "Wykryto: ${uniq_tmp%'; '}"
else
    record_check "PASS" "Pliki .tmp" "Nie wykryto artefaktow .tmp"
fi

if command -v systemctl >/dev/null 2>&1; then
    for unit in "${REQUIRED_UNITS[@]}"; do
        active_state="$(systemctl is-active "${unit}" 2>/dev/null || true)"
        enabled_state="$(systemctl is-enabled "${unit}" 2>/dev/null || true)"
        if [ "${active_state}" = "active" ]; then
            record_check "PASS" "systemd ${unit}" "active=${active_state}; enabled=${enabled_state:-unknown}"
        else
            record_check "FAIL" "systemd ${unit}" "active=${active_state:-unknown}; enabled=${enabled_state:-unknown}"
        fi
    done
else
    record_check "FAIL" "systemd" "Brak polecenia systemctl"
fi

if command -v lsmod >/dev/null 2>&1; then
    if lsmod | awk '{print $1}' | grep -Fxq "g_mass_storage"; then
        record_check "PASS" "Modul g_mass_storage" "Zaladowany"
    else
        record_check "FAIL" "Modul g_mass_storage" "Nie jest zaladowany"
    fi
else
    record_check "FAIL" "Modul g_mass_storage" "Brak polecenia lsmod"
fi

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

normalize_path() {
    local raw_path="$1"
    if [ -e "${raw_path}" ] && command -v readlink >/dev/null 2>&1; then
        readlink -f "${raw_path}" 2>/dev/null || printf '%s' "${raw_path}"
        return
    fi
    printf '%s' "${raw_path}"
}

EXPECTED_IMAGE=""
case "${ACTIVE_SLOT}" in
    A) EXPECTED_IMAGE="${IMG_A}" ;;
    B) EXPECTED_IMAGE="${IMG_B}" ;;
esac

RUNTIME_LUN="$(resolve_runtime_lun 2>/dev/null || true)"
if [ -z "${EXPECTED_IMAGE}" ]; then
    record_check "FAIL" "Runtime LUN vs ACTIVE_SLOT" "Brak poprawnego ACTIVE_SLOT"
elif [ -z "${RUNTIME_LUN}" ]; then
    record_check "FAIL" "Runtime LUN vs ACTIVE_SLOT" "Nie mozna odczytac runtime LUN"
else
    runtime_norm="$(normalize_path "${RUNTIME_LUN}")"
    expected_norm="$(normalize_path "${EXPECTED_IMAGE}")"
    if [ "${RUNTIME_LUN}" = "${EXPECTED_IMAGE}" ] || [ "${runtime_norm}" = "${expected_norm}" ]; then
        record_check "PASS" "Runtime LUN vs ACTIVE_SLOT" "LUN=${RUNTIME_LUN}; ACTIVE_SLOT=${ACTIVE_SLOT}"
    else
        record_check "FAIL" "Runtime LUN vs ACTIVE_SLOT" "LUN=${RUNTIME_LUN}; oczekiwano=${EXPECTED_IMAGE}; ACTIVE_SLOT=${ACTIVE_SLOT}"
    fi
fi

OVERALL_STATUS="PASS"
if [ "${FAIL_COUNT}" -gt 0 ]; then
    OVERALL_STATUS="FAIL"
elif [ "${STRICT_MODE}" = true ] && [ "${WARN_COUNT}" -gt 0 ]; then
    OVERALL_STATUS="FAIL"
fi

if [ "${JSON_MODE}" = true ]; then
    if command -v python3 >/dev/null 2>&1; then
        python3 - "${CHECK_FILE}" "${OVERALL_STATUS}" "${STRICT_MODE}" "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}" <<'PY'
import json
import sys

check_file = sys.argv[1]
status = sys.argv[2]
strict_mode = sys.argv[3].lower() == "true"
pass_count = int(sys.argv[4])
warn_count = int(sys.argv[5])
fail_count = int(sys.argv[6])

checks = []
with open(check_file, "r", encoding="utf-8") as handle:
    for raw_line in handle:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        checks.append(
            {
                "status": parts[0],
                "name": parts[1],
                "detail": parts[2],
            }
        )

payload = {
    "status": status,
    "strict": strict_mode,
    "summary": {
        "pass": pass_count,
        "warn": warn_count,
        "fail": fail_count,
    },
    "checks": checks,
}

print(json.dumps(payload, ensure_ascii=True, indent=2))
PY
    else
        echo '{"status":"FAIL","error":"python3 not available for --json output"}'
        OVERALL_STATUS="FAIL"
    fi
else
    echo "=============================="
    echo " CNC INSTALL VALIDATION"
    echo "=============================="
    echo "Mode: SHADOW-only validation"
    echo "Strict mode: ${STRICT_MODE}"
    echo "PASS: ${PASS_COUNT}  WARN: ${WARN_COUNT}  FAIL: ${FAIL_COUNT}"
    echo "RESULT: ${OVERALL_STATUS}"
    echo ""
    while IFS=$'\t' read -r check_status check_name check_detail; do
        if [ -n "${check_detail}" ]; then
            printf '[%s] %s - %s\n' "${check_status}" "${check_name}" "${check_detail}"
        else
            printf '[%s] %s\n' "${check_status}" "${check_name}"
        fi
    done < "${CHECK_FILE}"
fi

if [ "${OVERALL_STATUS}" = "PASS" ]; then
    exit 0
fi
exit 1
