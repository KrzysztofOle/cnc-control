#!/bin/bash
set -u
set -o pipefail

VERBOSE=0
JSON_ONLY=0
CRITICAL_COUNT=0
WARN_COUNT=0

ENV_FILE="/etc/cnc-control/cnc-control.env"
MIN_USB_IMAGE_SIZE_BYTES=1048576

SECTIONS=("boot" "kernel" "gadget" "usb_image" "project_config" "shadow" "samba" "systemd" "runtime" "logs" "hardware")
SAMBA_DEFAULT_SHARE_PATH="/mnt/cnc_usb"

REPORT_STATUS=()
REPORT_MESSAGE=()
REPORT_DETAIL=()
SECTION_STATUS=()
SECTION_CHECKS_JSON=()

trim_string() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "${value}"
}

json_escape() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//$'\n'/\\n}"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    printf '%s' "${value}"
}

compact_output() {
    local value="$1"
    value="$(printf '%s' "${value}" | tr '\n' ';')"
    value="$(trim_string "${value}")"
    printf '%s' "${value}"
}

section_index() {
    case "$1" in
        boot) printf '0' ;;
        kernel) printf '1' ;;
        gadget) printf '2' ;;
        usb_image) printf '3' ;;
        project_config) printf '4' ;;
        shadow) printf '5' ;;
        samba) printf '6' ;;
        systemd) printf '7' ;;
        runtime) printf '8' ;;
        logs) printf '9' ;;
        hardware) printf '10' ;;
        *) printf '%s' "-1" ;;
    esac
}

append_report() {
    REPORT_STATUS+=("$1")
    REPORT_MESSAGE+=("$2")
    REPORT_DETAIL+=("$3")
}

update_section_status() {
    local section="$1"
    local status="$2"
    local idx=""
    local current=""

    idx="$(section_index "${section}")"
    if [ "${idx}" -lt 0 ]; then
        return
    fi

    current="${SECTION_STATUS[$idx]}"
    if [ "${status}" = "FAIL" ]; then
        SECTION_STATUS[$idx]="FAIL"
        return
    fi

    if [ "${status}" = "WARN" ] && [ "${current}" != "FAIL" ]; then
        SECTION_STATUS[$idx]="WARN"
    fi
}

append_section_check_json() {
    local section="$1"
    local name="$2"
    local status="$3"
    local severity="$4"
    local detail="$5"
    local idx=""
    local entry=""

    idx="$(section_index "${section}")"
    if [ "${idx}" -lt 0 ]; then
        return
    fi

    entry="{\"name\":\"$(json_escape "${name}")\",\"status\":\"${status}\",\"severity\":\"${severity}\",\"detail\":\"$(json_escape "${detail}")\"}"

    if [ -n "${SECTION_CHECKS_JSON[$idx]}" ]; then
        SECTION_CHECKS_JSON[$idx]+=","
    fi
    SECTION_CHECKS_JSON[$idx]+="${entry}"
}

add_check() {
    local section="$1"
    local severity="$2"
    local status="$3"
    local message="$4"
    local detail="${5:-}"

    if [ "${status}" = "FAIL" ] && [ "${severity}" = "CRITICAL" ]; then
        CRITICAL_COUNT=$((CRITICAL_COUNT + 1))
    fi
    if [ "${status}" = "WARN" ]; then
        WARN_COUNT=$((WARN_COUNT + 1))
    fi

    append_report "${status}" "${message}" "${detail}"
    update_section_status "${section}" "${status}"
    append_section_check_json "${section}" "${message}" "${status}" "${severity}" "${detail}"
}

init_sections() {
    local idx=0
    for idx in "${!SECTIONS[@]}"; do
        SECTION_STATUS[$idx]="PASS"
        SECTION_CHECKS_JSON[$idx]=""
    done
}

resolve_boot_file() {
    local candidate=""
    for candidate in "$@"; do
        if [ -f "${candidate}" ]; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done
    return 1
}

resolve_active_boot_file() {
    local candidate=""
    local mount_dir=""

    for candidate in "$@"; do
        if [ ! -f "${candidate}" ]; then
            continue
        fi

        mount_dir="$(dirname "${candidate}")"
        if awk -v p="${mount_dir}" '$2 == p { found=1 } END { exit !found }' /proc/mounts 2>/dev/null; then
            printf '%s\n' "${candidate}"
            return 0
        fi
    done

    resolve_boot_file "$@"
}

get_env_value() {
    local file_path="$1"
    local key="$2"

    awk -v key="${key}" '
        function ltrim(v) { sub(/^[ \t\r\n]+/, "", v); return v }
        function rtrim(v) { sub(/[ \t\r\n]+$/, "", v); return v }
        function trim(v)  { return rtrim(ltrim(v)) }
        BEGIN { found = 0 }
        /^[ \t]*#/ { next }
        {
            if (match($0, "^[ \t]*(export[ \t]+)?" key "[ \t]*=")) {
                found = 1
                line = $0
                sub("^[ \t]*(export[ \t]+)?" key "[ \t]*=[ \t]*", "", line)
                line = trim(line)
                if (line ~ /^".*"$/ || line ~ /^'\''.*'\''$/) {
                    line = substr(line, 2, length(line) - 2)
                } else {
                    sub(/[ \t]+#.*/, "", line)
                    line = trim(line)
                }
                print line
                exit 0
            }
        }
        END {
            if (!found) {
                exit 1
            }
        }
    ' "${file_path}"
}

get_env_value_or_default() {
    local file_path="$1"
    local key="$2"
    local default_value="$3"
    local value=""

    value="$(get_env_value "${file_path}" "${key}" 2>/dev/null || true)"
    value="$(trim_string "${value}")"
    if [ -n "${value}" ]; then
        printf '%s' "${value}"
    else
        printf '%s' "${default_value}"
    fi
}

get_samba_share_path() {
    local conf_file="$1"
    local share_name="${2:-cnc_usb}"

    if [ ! -f "${conf_file}" ]; then
        return 1
    fi

    awk -v share="${share_name}" '
        BEGIN { in_share = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            line = $0
            gsub(/^[[:space:]]*\[/, "", line)
            gsub(/\][[:space:]]*$/, "", line)
            in_share = (tolower(line) == tolower(share))
            next
        }
        in_share && /^[[:space:]]*path[[:space:]]*=/ {
            line = $0
            sub(/^[[:space:]]*path[[:space:]]*=[[:space:]]*/, "", line)
            sub(/[[:space:]]*#.*/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            print line
            exit 0
        }
    ' "${conf_file}"
}

get_samba_option() {
    local conf_file="$1"
    local section_name="$2"
    local option_name="$3"

    if [ ! -f "${conf_file}" ]; then
        return 1
    fi

    awk -v section="${section_name}" -v option="${option_name}" '
        BEGIN { in_section = 0; target = tolower(option) }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            line = $0
            gsub(/^[[:space:]]*\[/, "", line)
            gsub(/\][[:space:]]*$/, "", line)
            in_section = (tolower(line) == tolower(section))
            next
        }
        !in_section { next }
        {
            split($0, kv, "=")
            if (length(kv) < 2) {
                next
            }
            key = kv[1]
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            if (tolower(key) != target) {
                next
            }
            value = substr($0, index($0, "=") + 1)
            sub(/[[:space:]]*#.*/, "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print value
            exit 0
        }
    ' "${conf_file}"
}

is_true_value() {
    local raw="$1"
    local normalized=""

    normalized="$(printf '%s' "${raw}" | tr '[:upper:]' '[:lower:]')"
    case "${normalized}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

is_shadow_enabled() {
    local value=""

    if [ ! -f "${ENV_FILE}" ]; then
        return 1
    fi
    value="$(get_env_value "${ENV_FILE}" "CNC_SHADOW_ENABLED" 2>/dev/null || true)"
    value="$(trim_string "${value}")"
    if [ -z "${value}" ]; then
        return 1
    fi
    is_true_value "${value}"
}

resolve_command_path() {
    local binary_name="$1"
    local candidate=""

    if candidate="$(command -v "${binary_name}" 2>/dev/null)"; then
        candidate="$(trim_string "${candidate}")"
        if [ -n "${candidate}" ]; then
            printf '%s' "${candidate}"
            return 0
        fi
    fi

    for candidate in "/usr/sbin/${binary_name}" "/sbin/${binary_name}" "/usr/bin/${binary_name}" "/bin/${binary_name}"; do
        if [ -x "${candidate}" ]; then
            printf '%s' "${candidate}"
            return 0
        fi
    done
    return 1
}

command_available() {
    local binary_name="$1"
    resolve_command_path "${binary_name}" >/dev/null 2>&1
}

normalize_path() {
    local path_value="$1"

    if [ -z "${path_value}" ]; then
        printf '%s' ""
        return 0
    fi

    if command -v readlink >/dev/null 2>&1; then
        local normalized=""
        normalized="$(readlink -f "${path_value}" 2>/dev/null || true)"
        normalized="$(trim_string "${normalized}")"
        if [ -n "${normalized}" ]; then
            printf '%s' "${normalized}"
            return 0
        fi
    fi

    printf '%s' "${path_value}"
}

file_size_bytes() {
    local file_path="$1"
    if stat -c %s "${file_path}" >/dev/null 2>&1; then
        stat -c %s "${file_path}"
        return 0
    fi
    if stat -f %z "${file_path}" >/dev/null 2>&1; then
        stat -f %z "${file_path}"
        return 0
    fi
    return 1
}

check_boot() {
    local config_file=""
    local cmdline_file=""
    local line_count=""
    local dwc2_line=""

    config_file="$(resolve_active_boot_file "/boot/firmware/config.txt" "/boot/config.txt" || true)"
    if [ -z "${config_file}" ]; then
        add_check "boot" "CRITICAL" "FAIL" "Boot overlay dwc2" "Missing /boot/config.txt (or /boot/firmware/config.txt)"
        add_check "boot" "CRITICAL" "FAIL" "Boot dwc2 peripheral mode" "Missing /boot/config.txt (or /boot/firmware/config.txt)"
    else
        dwc2_line="$(sed 's/[[:space:]]*#.*$//' "${config_file}" | grep -Ei '^[[:space:]]*dtoverlay[[:space:]]*=[[:space:]]*dwc2([[:space:]]*,.*)?[[:space:]]*$' | head -n 1 || true)"

        if [ -n "${dwc2_line}" ]; then
            add_check "boot" "CRITICAL" "PASS" "Boot overlay dwc2" "${config_file}"

            if printf '%s' "${dwc2_line}" | grep -Eiq 'dr_mode[[:space:]]*=[[:space:]]*host'; then
                add_check "boot" "CRITICAL" "FAIL" "Boot dwc2 peripheral mode" "Detected dr_mode=host in ${config_file}: ${dwc2_line}"
            elif printf '%s' "${dwc2_line}" | grep -Eiq 'dr_mode[[:space:]]*=[[:space:]]*peripheral'; then
                add_check "boot" "CRITICAL" "PASS" "Boot dwc2 peripheral mode" "${dwc2_line}"
            else
                add_check "boot" "CRITICAL" "FAIL" "Boot dwc2 peripheral mode" "Missing dr_mode=peripheral in ${config_file}: ${dwc2_line}"
            fi
        else
            add_check "boot" "CRITICAL" "FAIL" "Boot overlay dwc2" "No active dtoverlay=dwc2 in ${config_file}"
            add_check "boot" "CRITICAL" "FAIL" "Boot dwc2 peripheral mode" "Missing active dtoverlay=dwc2 in ${config_file}"
        fi
    fi

    cmdline_file="$(resolve_active_boot_file "/boot/firmware/cmdline.txt" "/boot/cmdline.txt" || true)"
    if [ -z "${cmdline_file}" ]; then
        add_check "boot" "CRITICAL" "FAIL" "Boot modules-load=dwc2" "Missing /boot/cmdline.txt (or /boot/firmware/cmdline.txt)"
        add_check "boot" "CRITICAL" "FAIL" "Boot cmdline single line" "Missing /boot/cmdline.txt (or /boot/firmware/cmdline.txt)"
        return
    fi

    if grep -Eq '(^|[[:space:]])modules-load=[^[:space:]]*dwc2[^[:space:]]*([[:space:]]|$)' "${cmdline_file}"; then
        add_check "boot" "CRITICAL" "PASS" "Boot modules-load=dwc2" "${cmdline_file}"
    else
        add_check "boot" "CRITICAL" "FAIL" "Boot modules-load=dwc2" "Missing modules-load=dwc2 in ${cmdline_file}"
    fi

    line_count="$(awk 'END {print NR}' "${cmdline_file}" 2>/dev/null || echo 0)"
    if [ "${line_count}" = "1" ]; then
        add_check "boot" "CRITICAL" "PASS" "Boot cmdline single line" "${cmdline_file}"
    else
        add_check "boot" "CRITICAL" "FAIL" "Boot cmdline single line" "Found ${line_count} lines in ${cmdline_file}"
    fi
}

check_kernel() {
    local udc_name=""

    if command -v lsmod >/dev/null 2>&1 && lsmod | awk '{print $1}' | grep -qx "dwc2"; then
        add_check "kernel" "CRITICAL" "PASS" "Kernel module dwc2" "Loaded"
    else
        add_check "kernel" "CRITICAL" "FAIL" "Kernel module dwc2" "Module dwc2 not loaded"
    fi

    if [ -d "/sys/class/udc" ]; then
        udc_name="$(ls -A "/sys/class/udc" 2>/dev/null | head -n 1 || true)"
        if [ -n "${udc_name}" ]; then
            add_check "kernel" "CRITICAL" "PASS" "UDC detected" "${udc_name}"
        else
            add_check "kernel" "CRITICAL" "FAIL" "UDC detected" "/sys/class/udc is empty"
        fi
    else
        add_check "kernel" "CRITICAL" "FAIL" "UDC detected" "/sys/class/udc does not exist"
    fi

    if [ -d "/sys/kernel/config" ]; then
        add_check "kernel" "CRITICAL" "PASS" "Configfs available" "/sys/kernel/config"
    else
        add_check "kernel" "CRITICAL" "FAIL" "Configfs available" "/sys/kernel/config not found"
    fi
}

check_gadget() {
    local gadget_dir="/sys/kernel/config/usb_gadget/g1"
    local udc_file="${gadget_dir}/UDC"
    local lun_file="${gadget_dir}/functions/mass_storage.0/lun.0/file"
    local udc_value=""
    local image_path=""

    if command -v lsmod >/dev/null 2>&1 && lsmod | awk '{print $1}' | grep -qx "g_mass_storage"; then
        add_check "gadget" "CRITICAL" "PASS" "USB gadget g_mass_storage loaded" "Loaded"
        return
    fi

    if [ ! -d "${gadget_dir}" ]; then
        add_check "gadget" "CRITICAL" "FAIL" "USB gadget g1 present" "${gadget_dir} not found and g_mass_storage is not loaded"
        return
    fi
    add_check "gadget" "CRITICAL" "PASS" "USB gadget g1 present" "${gadget_dir}"

    if [ -f "${udc_file}" ]; then
        udc_value="$(tr -d '[:space:]' < "${udc_file}" 2>/dev/null || true)"
        if [ -n "${udc_value}" ]; then
            add_check "gadget" "CRITICAL" "PASS" "Gadget UDC bound" "${udc_value}"
        else
            add_check "gadget" "CRITICAL" "FAIL" "Gadget UDC bound" "${udc_file} is empty"
        fi
    else
        add_check "gadget" "CRITICAL" "FAIL" "Gadget UDC bound" "Missing ${udc_file}"
    fi

    if [ -d "${gadget_dir}/functions/mass_storage.0" ]; then
        add_check "gadget" "CRITICAL" "PASS" "Gadget mass_storage.0 present" "${gadget_dir}/functions/mass_storage.0"
    else
        add_check "gadget" "CRITICAL" "FAIL" "Gadget mass_storage.0 present" "Missing ${gadget_dir}/functions/mass_storage.0"
    fi

    if [ -f "${lun_file}" ]; then
        image_path="$(tr -d '\r\n' < "${lun_file}" 2>/dev/null || true)"
        image_path="$(trim_string "${image_path}")"
        if [ -z "${image_path}" ]; then
            add_check "gadget" "CRITICAL" "FAIL" "Gadget LUN file path valid" "${lun_file} is empty"
        elif [ -e "${image_path}" ]; then
            add_check "gadget" "CRITICAL" "PASS" "Gadget LUN file path valid" "${image_path}"
        else
            add_check "gadget" "CRITICAL" "FAIL" "Gadget LUN file path valid" "Target file does not exist: ${image_path}"
        fi
    else
        add_check "gadget" "CRITICAL" "FAIL" "Gadget LUN file path valid" "Missing ${lun_file}"
    fi
}

check_usb_image() {
    local image_path=""
    local size_bytes=""
    local file_info=""
    local fsck_output=""
    local fsck_rc=0
    local file_bin=""
    local fsck_bin=""

    if is_shadow_enabled; then
        add_check "usb_image" "WARN" "PASS" "USB image legacy path" "SHADOW enabled; using CNC_USB_IMG_A/CNC_USB_IMG_B"
        return
    fi

    if [ ! -f "${ENV_FILE}" ]; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image path configured" "Missing ${ENV_FILE}"
        return
    fi

    image_path="$(get_env_value "${ENV_FILE}" "CNC_USB_IMG" 2>/dev/null || true)"
    image_path="$(trim_string "${image_path}")"
    if [ -z "${image_path}" ]; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image path configured" "CNC_USB_IMG is empty in ${ENV_FILE}"
        return
    fi
    add_check "usb_image" "CRITICAL" "PASS" "USB image path configured" "${image_path}"

    if [ ! -f "${image_path}" ]; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image file exists" "Missing file: ${image_path}"
        return
    fi
    add_check "usb_image" "CRITICAL" "PASS" "USB image file exists" "${image_path}"

    size_bytes="$(file_size_bytes "${image_path}" 2>/dev/null || true)"
    if [ -z "${size_bytes}" ]; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image size > 1MB" "Unable to read file size"
    elif [ "${size_bytes}" -gt "${MIN_USB_IMAGE_SIZE_BYTES}" ]; then
        add_check "usb_image" "CRITICAL" "PASS" "USB image size > 1MB" "${size_bytes} bytes"
    else
        add_check "usb_image" "CRITICAL" "FAIL" "USB image size > 1MB" "Current size: ${size_bytes} bytes"
    fi

    file_bin="$(resolve_command_path "file" || true)"
    if [ -z "${file_bin}" ]; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image FAT type" "Command 'file' not available"
    else
        file_info="$("${file_bin}" -b "${image_path}" 2>/dev/null || true)"
        if printf '%s' "${file_info}" | grep -Eiq 'fat'; then
            add_check "usb_image" "CRITICAL" "PASS" "USB image FAT type" "${file_info}"
        else
            add_check "usb_image" "CRITICAL" "FAIL" "USB image FAT type" "${file_info}"
        fi
    fi

    fsck_bin="$(resolve_command_path "fsck.vfat" || true)"
    if [ -z "${fsck_bin}" ]; then
        add_check "usb_image" "WARN" "WARN" "USB image fsck check" "Command fsck.vfat not available"
        return
    fi

    fsck_output="$("${fsck_bin}" -n "${image_path}" 2>&1)"
    fsck_rc=$?
    fsck_output="$(compact_output "${fsck_output}")"

    if [ "${fsck_rc}" -eq 0 ]; then
        add_check "usb_image" "CRITICAL" "PASS" "USB image fsck check" "${fsck_output}"
    elif [ "${fsck_rc}" -eq 1 ]; then
        add_check "usb_image" "WARN" "WARN" "USB image fsck check" "${fsck_output}"
    else
        add_check "usb_image" "CRITICAL" "FAIL" "USB image fsck check" "fsck.vfat rc=${fsck_rc}; ${fsck_output}"
    fi
}

check_project_config() {
    local value=""

    if [ ! -f "${ENV_FILE}" ]; then
        add_check "project_config" "CRITICAL" "FAIL" "Project env file present" "Missing ${ENV_FILE}"
        return
    fi
    add_check "project_config" "CRITICAL" "PASS" "Project env file present" "${ENV_FILE}"

    if is_shadow_enabled; then
        value="$(get_env_value_or_default "${ENV_FILE}" "CNC_MASTER_DIR" "/var/lib/cnc-control/master")"
        value="$(trim_string "${value}")"
        if [ -n "${value}" ]; then
            add_check "project_config" "CRITICAL" "PASS" "Config variable CNC_MASTER_DIR" "${value}"
            if [ -d "${value}" ]; then
                add_check "project_config" "CRITICAL" "PASS" "Master directory exists" "${value}"
            else
                add_check "project_config" "CRITICAL" "FAIL" "Master directory exists" "Missing directory: ${value}"
            fi
        else
            add_check "project_config" "CRITICAL" "FAIL" "Config variable CNC_MASTER_DIR" "Missing or empty in ${ENV_FILE}"
        fi
        return
    fi

    value="$(get_env_value "${ENV_FILE}" "CNC_USB_IMG" 2>/dev/null || true)"
    value="$(trim_string "${value}")"
    if [ -n "${value}" ]; then
        add_check "project_config" "CRITICAL" "PASS" "Config variable CNC_USB_IMG" "${value}"
    else
        add_check "project_config" "CRITICAL" "FAIL" "Config variable CNC_USB_IMG" "Missing or empty in ${ENV_FILE}"
    fi

    value="$(get_env_value "${ENV_FILE}" "CNC_MOUNT_POINT" 2>/dev/null || true)"
    value="$(trim_string "${value}")"
    if [ -n "${value}" ]; then
        add_check "project_config" "CRITICAL" "PASS" "Config variable CNC_MOUNT_POINT" "${value}"
    else
        add_check "project_config" "CRITICAL" "FAIL" "Config variable CNC_MOUNT_POINT" "Missing or empty in ${ENV_FILE}"
    fi

    value="$(get_env_value "${ENV_FILE}" "CNC_UPLOAD_DIR" 2>/dev/null || true)"
    value="$(trim_string "${value}")"
    if [ -n "${value}" ]; then
        add_check "project_config" "CRITICAL" "PASS" "Config variable CNC_UPLOAD_DIR" "${value}"
        if [ -d "${value}" ]; then
            add_check "project_config" "CRITICAL" "PASS" "Upload directory exists" "${value}"
        else
            add_check "project_config" "CRITICAL" "FAIL" "Upload directory exists" "Missing directory: ${value}"
        fi
    else
        add_check "project_config" "CRITICAL" "FAIL" "Config variable CNC_UPLOAD_DIR" "Missing or empty in ${ENV_FILE}"
    fi
}

check_shadow() {
    local shadow_enabled_raw=""
    local shadow_state_file=""
    local shadow_history_file=""
    local slot_file=""
    local lock_file=""
    local master_dir=""
    local image_a=""
    local image_b=""
    local size_bytes=""
    local active_slot_value=""
    local state_validation_output=""
    local state_validation_rc=0
    local history_validation_output=""
    local history_validation_rc=0

    if [ ! -f "${ENV_FILE}" ]; then
        add_check "shadow" "WARN" "WARN" "Shadow checks available" "Missing ${ENV_FILE}"
        return
    fi

    shadow_enabled_raw="$(get_env_value "${ENV_FILE}" "CNC_SHADOW_ENABLED" 2>/dev/null || true)"
    shadow_enabled_raw="$(trim_string "${shadow_enabled_raw}")"

    if ! is_true_value "${shadow_enabled_raw}"; then
        add_check "shadow" "WARN" "PASS" "Tryb SHADOW wlaczony" "false (pomijam walidacje SHADOW)"
        return
    fi
    add_check "shadow" "CRITICAL" "PASS" "Tryb SHADOW wlaczony" "true"

    master_dir="$(get_env_value_or_default "${ENV_FILE}" "CNC_MASTER_DIR" "/var/lib/cnc-control/master")"
    if [ -d "${master_dir}" ]; then
        add_check "shadow" "CRITICAL" "PASS" "Katalog CNC_MASTER_DIR" "${master_dir}"
    else
        add_check "shadow" "CRITICAL" "FAIL" "Katalog CNC_MASTER_DIR" "Missing directory: ${master_dir}"
    fi

    image_a="$(get_env_value_or_default "${ENV_FILE}" "CNC_USB_IMG_A" "/var/lib/cnc-control/cnc_usb_a.img")"
    image_b="$(get_env_value_or_default "${ENV_FILE}" "CNC_USB_IMG_B" "/var/lib/cnc-control/cnc_usb_b.img")"
    if [ -f "${image_a}" ]; then
        add_check "shadow" "CRITICAL" "PASS" "Shadow image slot A exists" "${image_a}"
        size_bytes="$(file_size_bytes "${image_a}" 2>/dev/null || true)"
        if [ -n "${size_bytes}" ] && [ "${size_bytes}" -gt "${MIN_USB_IMAGE_SIZE_BYTES}" ]; then
            add_check "shadow" "CRITICAL" "PASS" "Shadow image slot A size > 1MB" "${size_bytes} bytes"
        else
            add_check "shadow" "CRITICAL" "FAIL" "Shadow image slot A size > 1MB" "Current size: ${size_bytes:-unknown}"
        fi
    else
        add_check "shadow" "CRITICAL" "FAIL" "Shadow image slot A exists" "Missing file: ${image_a}"
    fi

    if [ -f "${image_b}" ]; then
        add_check "shadow" "CRITICAL" "PASS" "Shadow image slot B exists" "${image_b}"
        size_bytes="$(file_size_bytes "${image_b}" 2>/dev/null || true)"
        if [ -n "${size_bytes}" ] && [ "${size_bytes}" -gt "${MIN_USB_IMAGE_SIZE_BYTES}" ]; then
            add_check "shadow" "CRITICAL" "PASS" "Shadow image slot B size > 1MB" "${size_bytes} bytes"
        else
            add_check "shadow" "CRITICAL" "FAIL" "Shadow image slot B size > 1MB" "Current size: ${size_bytes:-unknown}"
        fi
    else
        add_check "shadow" "CRITICAL" "FAIL" "Shadow image slot B exists" "Missing file: ${image_b}"
    fi

    slot_file="$(get_env_value_or_default "${ENV_FILE}" "CNC_ACTIVE_SLOT_FILE" "/var/lib/cnc-control/shadow_active_slot.state")"
    if [ -f "${slot_file}" ]; then
        active_slot_value="$(tr -d '\r\n\t ' < "${slot_file}" 2>/dev/null || true)"
        active_slot_value="$(printf '%s' "${active_slot_value}" | tr '[:lower:]' '[:upper:]')"
        if [ "${active_slot_value}" = "A" ] || [ "${active_slot_value}" = "B" ]; then
            add_check "shadow" "CRITICAL" "PASS" "CNC_ACTIVE_SLOT_FILE valid" "${slot_file}: ${active_slot_value}"
        else
            add_check "shadow" "CRITICAL" "FAIL" "CNC_ACTIVE_SLOT_FILE valid" "${slot_file}: invalid value '${active_slot_value}'"
        fi
    else
        add_check "shadow" "CRITICAL" "FAIL" "CNC_ACTIVE_SLOT_FILE valid" "Missing file: ${slot_file}"
    fi

    shadow_state_file="$(get_env_value_or_default "${ENV_FILE}" "CNC_SHADOW_STATE_FILE" "/var/lib/cnc-control/shadow_state.json")"
    if [ ! -f "${shadow_state_file}" ]; then
        add_check "shadow" "CRITICAL" "FAIL" "CNC_SHADOW_STATE_FILE present" "Missing file: ${shadow_state_file}"
    elif ! command -v python3 >/dev/null 2>&1; then
        add_check "shadow" "CRITICAL" "FAIL" "CNC_SHADOW_STATE_FILE valid JSON" "Command python3 not available"
    else
        state_validation_output="$(python3 - "${shadow_state_file}" "${slot_file}" <<'PY'
import json
import sys

state_path = sys.argv[1]
slot_path = sys.argv[2]

allowed_states = {
    "IDLE",
    "CHANGE_DETECTED",
    "BUILD_SLOT_A",
    "BUILD_SLOT_B",
    "EXPORT_STOP",
    "EXPORT_START",
    "READY",
    "ERROR",
}

with open(state_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
if not isinstance(payload, dict):
    raise SystemExit("State file must contain JSON object")

fsm_state = str(payload.get("fsm_state", ""))
if fsm_state not in allowed_states:
    raise SystemExit(f"Invalid fsm_state: {fsm_state}")

active_slot = str(payload.get("active_slot", ""))
if active_slot not in {"A", "B"}:
    raise SystemExit(f"Invalid active_slot: {active_slot}")

rebuild_slot = payload.get("rebuild_slot")
if rebuild_slot not in {"A", "B", None}:
    raise SystemExit(f"Invalid rebuild_slot: {rebuild_slot}")

run_id = payload.get("run_id")
if not isinstance(run_id, int) or run_id < 0:
    raise SystemExit(f"Invalid run_id: {run_id}")

rebuild_counter = payload.get("rebuild_counter", run_id)
if not isinstance(rebuild_counter, int) or rebuild_counter != run_id:
    raise SystemExit(f"Invalid rebuild_counter: {rebuild_counter} (expected {run_id})")

last_error = payload.get("last_error")
if last_error is not None and not isinstance(last_error, dict):
    raise SystemExit("Invalid last_error type")
if fsm_state == "ERROR" and not isinstance(last_error, dict):
    raise SystemExit("fsm_state=ERROR requires last_error object")

slot_value = None
try:
    with open(slot_path, "r", encoding="utf-8") as slot_handle:
        slot_value = slot_handle.read().strip().upper()
except FileNotFoundError:
    slot_value = None

if slot_value is not None and slot_value in {"A", "B"} and fsm_state in {"IDLE", "READY"}:
    if active_slot != slot_value:
        raise SystemExit(
            f"active_slot mismatch in stable state: state={active_slot}, slot_file={slot_value}, fsm_state={fsm_state}"
        )

print(f"fsm_state={fsm_state}; active_slot={active_slot}; run_id={run_id}")
PY
)"
        state_validation_rc=$?
        state_validation_output="$(compact_output "${state_validation_output}")"
        if [ "${state_validation_rc}" -eq 0 ]; then
            add_check "shadow" "CRITICAL" "PASS" "CNC_SHADOW_STATE_FILE valid JSON" "${state_validation_output}"
        else
            add_check "shadow" "CRITICAL" "FAIL" "CNC_SHADOW_STATE_FILE valid JSON" "${state_validation_output}"
        fi
    fi

    lock_file="$(get_env_value_or_default "${ENV_FILE}" "CNC_SHADOW_LOCK_FILE" "/var/run/cnc-shadow.lock")"
    if [ -f "${lock_file}" ]; then
        add_check "shadow" "WARN" "PASS" "CNC_SHADOW_LOCK_FILE present" "${lock_file}"
    else
        if [ -w "$(dirname "${lock_file}")" ]; then
            add_check "shadow" "WARN" "PASS" "CNC_SHADOW_LOCK_FILE present" "Lock file not created yet: ${lock_file}"
        else
            add_check "shadow" "WARN" "PASS" "CNC_SHADOW_LOCK_FILE present" "No write access to $(dirname "${lock_file}") (fallback /tmp expected)"
        fi
    fi

    shadow_history_file="$(get_env_value_or_default "${ENV_FILE}" "CNC_SHADOW_HISTORY_FILE" "/var/lib/cnc-control/shadow_history.json")"
    if [ ! -f "${shadow_history_file}" ]; then
        add_check "shadow" "WARN" "WARN" "CNC_SHADOW_HISTORY_FILE present" "Missing file: ${shadow_history_file}"
    elif ! command -v python3 >/dev/null 2>&1; then
        add_check "shadow" "WARN" "WARN" "CNC_SHADOW_HISTORY_FILE valid JSON" "Command python3 not available"
    else
        history_validation_output="$(python3 - "${shadow_history_file}" <<'PY'
import json
import sys

history_path = sys.argv[1]
with open(history_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)

if not isinstance(payload, list):
    raise SystemExit("History file must contain JSON array")

for index, entry in enumerate(payload):
    if not isinstance(entry, dict):
        raise SystemExit(f"Entry #{index} is not an object")
    run_id = entry.get("run_id")
    if run_id is not None and not isinstance(run_id, int):
        raise SystemExit(f"Entry #{index} has non-integer run_id: {run_id}")

print(f"entries={len(payload)}")
PY
)"
        history_validation_rc=$?
        history_validation_output="$(compact_output "${history_validation_output}")"
        if [ "${history_validation_rc}" -eq 0 ]; then
            add_check "shadow" "WARN" "PASS" "CNC_SHADOW_HISTORY_FILE valid JSON" "${history_validation_output}"
        else
            add_check "shadow" "WARN" "WARN" "CNC_SHADOW_HISTORY_FILE valid JSON" "${history_validation_output}"
        fi
    fi

    if command_available "inotifywait"; then
        add_check "shadow" "CRITICAL" "PASS" "Dependency inotifywait" "available"
    else
        add_check "shadow" "CRITICAL" "FAIL" "Dependency inotifywait" "command not found"
    fi
    if command_available "mkfs.vfat"; then
        add_check "shadow" "CRITICAL" "PASS" "Dependency mkfs.vfat" "available"
    else
        add_check "shadow" "CRITICAL" "FAIL" "Dependency mkfs.vfat" "command not found"
    fi
    if command_available "mcopy"; then
        add_check "shadow" "CRITICAL" "PASS" "Dependency mcopy" "available"
    else
        add_check "shadow" "CRITICAL" "FAIL" "Dependency mcopy" "command not found"
    fi
}

check_samba_unit() {
    local unit="$1"
    local expect_active="$2"
    local expect_enabled="$3"
    local active_state=""
    local enabled_state=""

    if ! command -v systemctl >/dev/null 2>&1; then
        add_check "samba" "WARN" "WARN" "${unit} state" "systemctl not available"
        return
    fi

    active_state="$(systemctl is-active "${unit}" 2>&1 || true)"
    enabled_state="$(systemctl is-enabled "${unit}" 2>&1 || true)"
    active_state="$(trim_string "${active_state}")"
    enabled_state="$(trim_string "${enabled_state}")"

    if [ "${active_state}" = "not-found" ] || [ "${enabled_state}" = "not-found" ]; then
        add_check "samba" "WARN" "PASS" "${unit} available" "not-found (pakiet/usluga nieobecna)"
        return
    fi

    if [ "${expect_active}" = "active" ]; then
        if [ "${active_state}" = "active" ]; then
            add_check "samba" "WARN" "PASS" "${unit} active" "${active_state}"
        else
            add_check "samba" "WARN" "WARN" "${unit} active" "${active_state}"
        fi
    else
        if [ "${active_state}" = "active" ]; then
            add_check "samba" "WARN" "WARN" "${unit} active" "${active_state}; expected inactive"
        else
            add_check "samba" "WARN" "PASS" "${unit} active" "${active_state}"
        fi
    fi

    if [ "${expect_enabled}" = "enabled" ]; then
        if [ "${enabled_state}" = "enabled" ]; then
            add_check "samba" "WARN" "PASS" "${unit} enabled" "${enabled_state}"
        else
            add_check "samba" "WARN" "WARN" "${unit} enabled" "${enabled_state}"
        fi
    else
        case "${enabled_state}" in
            disabled|masked|static|indirect|generated|alias)
                add_check "samba" "WARN" "PASS" "${unit} enabled" "${enabled_state}"
                ;;
            enabled)
                if [ "${active_state}" != "active" ]; then
                    add_check "samba" "WARN" "PASS" "${unit} enabled" "${enabled_state}; tolerated because service is inactive"
                else
                    add_check "samba" "WARN" "WARN" "${unit} enabled" "${enabled_state}; expected disabled/masked"
                fi
                ;;
            *)
                add_check "samba" "WARN" "WARN" "${unit} enabled" "${enabled_state}; expected disabled/masked"
                ;;
        esac
    fi
}

check_samba() {
    local samba_conf="/etc/samba/smb.conf"
    local shadow_enabled=0
    local expected_path=""
    local share_path=""
    local read_only_value=""
    local guest_ok_value=""
    local smb_ports_value=""
    local force_user_value=""
    local force_group_value=""
    local share_owner_user=""
    local share_owner_group=""

    if is_shadow_enabled; then
        shadow_enabled=1
    fi

    if [ "${shadow_enabled}" -eq 1 ]; then
        expected_path="$(get_env_value_or_default "${ENV_FILE}" "CNC_MASTER_DIR" "/var/lib/cnc-control/master")"
    else
        expected_path="$(get_env_value "${ENV_FILE}" "CNC_UPLOAD_DIR" 2>/dev/null || true)"
        expected_path="$(trim_string "${expected_path}")"
        if [ -z "${expected_path}" ]; then
            expected_path="$(get_env_value "${ENV_FILE}" "CNC_MOUNT_POINT" 2>/dev/null || true)"
            expected_path="$(trim_string "${expected_path}")"
        fi
        if [ -z "${expected_path}" ]; then
            expected_path="${SAMBA_DEFAULT_SHARE_PATH}"
        fi
    fi
    expected_path="$(trim_string "${expected_path}")"

    if [ ! -f "${samba_conf}" ]; then
        add_check "samba" "WARN" "WARN" "Samba config file present" "Missing ${samba_conf}"
        check_samba_unit "smbd.service" "active" "enabled"
        check_samba_unit "nmbd.service" "inactive" "disabled"
        check_samba_unit "samba-ad-dc.service" "inactive" "disabled"
        return
    fi
    add_check "samba" "WARN" "PASS" "Samba config file present" "${samba_conf}"

    share_path="$(get_samba_share_path "${samba_conf}" "cnc_usb" 2>/dev/null || true)"
    share_path="$(trim_string "${share_path}")"
    if [ -z "${share_path}" ]; then
        add_check "samba" "WARN" "WARN" "Samba share cnc_usb path" "No path entry found"
    elif [ "${share_path}" = "${expected_path}" ]; then
        add_check "samba" "WARN" "PASS" "Samba share cnc_usb path" "${share_path}"
    else
        add_check "samba" "WARN" "WARN" "Samba share cnc_usb path" "${share_path}; expected ${expected_path}"
    fi

    read_only_value="$(get_samba_option "${samba_conf}" "cnc_usb" "read only" 2>/dev/null || true)"
    read_only_value="$(printf '%s' "${read_only_value}" | tr '[:upper:]' '[:lower:]')"
    if [ "${read_only_value}" = "no" ]; then
        add_check "samba" "WARN" "PASS" "Samba share cnc_usb read only" "no"
    else
        add_check "samba" "WARN" "WARN" "Samba share cnc_usb read only" "${read_only_value:-missing}; expected no"
    fi

    guest_ok_value="$(get_samba_option "${samba_conf}" "cnc_usb" "guest ok" 2>/dev/null || true)"
    guest_ok_value="$(printf '%s' "${guest_ok_value}" | tr '[:upper:]' '[:lower:]')"
    if [ "${guest_ok_value}" = "yes" ]; then
        add_check "samba" "WARN" "PASS" "Samba share cnc_usb guest ok" "yes"
    else
        add_check "samba" "WARN" "WARN" "Samba share cnc_usb guest ok" "${guest_ok_value:-missing}; expected yes"
    fi

    smb_ports_value="$(get_samba_option "${samba_conf}" "global" "smb ports" 2>/dev/null || true)"
    smb_ports_value="$(trim_string "${smb_ports_value}")"
    if [ "${smb_ports_value}" = "445" ]; then
        add_check "samba" "WARN" "PASS" "Samba global smb ports" "${smb_ports_value}"
    else
        add_check "samba" "WARN" "WARN" "Samba global smb ports" "${smb_ports_value:-missing}; expected 445"
    fi

    if command_available "ss"; then
        if ss -ltn 2>/dev/null | awk 'NR > 1 && $1 == "LISTEN" && $4 ~ /:445$/ { found = 1 } END { exit(found ? 0 : 1) }'; then
            add_check "samba" "WARN" "PASS" "Samba listen port 445" "LISTEN"
        else
            add_check "samba" "WARN" "WARN" "Samba listen port 445" "No listener on 445"
        fi
    else
        add_check "samba" "WARN" "WARN" "Samba listen port 445" "Command ss not available"
    fi

    check_samba_unit "smbd.service" "active" "enabled"
    check_samba_unit "nmbd.service" "inactive" "disabled"
    check_samba_unit "samba-ad-dc.service" "inactive" "disabled"

    if [ "${shadow_enabled}" -eq 1 ] && [ -n "${share_path}" ] && [ -e "${share_path}" ]; then
        force_user_value="$(get_samba_option "${samba_conf}" "cnc_usb" "force user" 2>/dev/null || true)"
        force_group_value="$(get_samba_option "${samba_conf}" "cnc_usb" "force group" 2>/dev/null || true)"
        force_user_value="$(trim_string "${force_user_value}")"
        force_group_value="$(trim_string "${force_group_value}")"
        share_owner_user="$(stat -c %U "${share_path}" 2>/dev/null || true)"
        share_owner_group="$(stat -c %G "${share_path}" 2>/dev/null || true)"
        share_owner_user="$(trim_string "${share_owner_user}")"
        share_owner_group="$(trim_string "${share_owner_group}")"

        if [ -n "${force_user_value}" ] && [ "${force_user_value}" = "${share_owner_user}" ]; then
            add_check "samba" "WARN" "PASS" "Samba share cnc_usb force user" "${force_user_value}"
        else
            add_check "samba" "WARN" "WARN" "Samba share cnc_usb force user" "${force_user_value:-missing}; expected ${share_owner_user}"
        fi

        if [ -n "${force_group_value}" ] && [ "${force_group_value}" = "${share_owner_group}" ]; then
            add_check "samba" "WARN" "PASS" "Samba share cnc_usb force group" "${force_group_value}"
        else
            add_check "samba" "WARN" "WARN" "Samba share cnc_usb force group" "${force_group_value:-missing}; expected ${share_owner_group}"
        fi
    fi
}

check_systemd_service() {
    local service_name="$1"
    local enabled_output=""
    local active_output=""
    local show_output=""
    local load_state=""
    local sub_state=""
    local result_state=""
    local n_restarts=""
    local exec_main_status=""
    local service_health_detail=""

    enabled_output="$(systemctl is-enabled "${service_name}" 2>&1 || true)"
    enabled_output="$(trim_string "${enabled_output}")"
    if [ "${enabled_output}" = "enabled" ]; then
        add_check "systemd" "WARN" "PASS" "${service_name} enabled" "${enabled_output}"
    else
        add_check "systemd" "WARN" "WARN" "${service_name} enabled" "${enabled_output}"
    fi

    active_output="$(systemctl is-active "${service_name}" 2>&1 || true)"
    active_output="$(trim_string "${active_output}")"
    if [ "${active_output}" = "active" ]; then
        add_check "systemd" "WARN" "PASS" "${service_name} active" "${active_output}"
    else
        add_check "systemd" "WARN" "WARN" "${service_name} active" "${active_output}"
    fi

    show_output="$(systemctl show "${service_name}" \
        --property=LoadState \
        --property=SubState \
        --property=Result \
        --property=NRestarts \
        --property=ExecMainStatus \
        2>/dev/null || true)"

    load_state="$(printf '%s\n' "${show_output}" | awk -F= '$1=="LoadState" { print $2; exit }')"
    sub_state="$(printf '%s\n' "${show_output}" | awk -F= '$1=="SubState" { print $2; exit }')"
    result_state="$(printf '%s\n' "${show_output}" | awk -F= '$1=="Result" { print $2; exit }')"
    n_restarts="$(printf '%s\n' "${show_output}" | awk -F= '$1=="NRestarts" { print $2; exit }')"
    exec_main_status="$(printf '%s\n' "${show_output}" | awk -F= '$1=="ExecMainStatus" { print $2; exit }')"

    load_state="$(trim_string "${load_state}")"
    sub_state="$(trim_string "${sub_state}")"
    result_state="$(trim_string "${result_state}")"
    n_restarts="$(trim_string "${n_restarts}")"
    exec_main_status="$(trim_string "${exec_main_status}")"
    service_health_detail="active=${active_output}; sub=${sub_state:-unknown}; result=${result_state:-unknown}; restarts=${n_restarts:-unknown}; exec=${exec_main_status:-unknown}"

    if [ "${load_state}" = "not-found" ]; then
        add_check "systemd" "CRITICAL" "FAIL" "${service_name} present" "LoadState=not-found"
        return
    fi

    if [ "${active_output}" != "active" ]; then
        add_check "systemd" "CRITICAL" "FAIL" "${service_name} runtime health" "${service_health_detail}"
        return
    fi

    case "${sub_state}" in
        running|listening|exited) ;;
        *)
            add_check "systemd" "CRITICAL" "FAIL" "${service_name} runtime health" "${service_health_detail}"
            return
            ;;
    esac

    if [ -n "${result_state}" ] && [ "${result_state}" != "success" ] && [ "${result_state}" != "done" ]; then
        add_check "systemd" "CRITICAL" "FAIL" "${service_name} runtime health" "${service_health_detail}"
        return
    fi

    if [ -n "${exec_main_status}" ] && [ "${exec_main_status}" != "0" ]; then
        add_check "systemd" "CRITICAL" "FAIL" "${service_name} runtime health" "${service_health_detail}"
        return
    fi

    add_check "systemd" "CRITICAL" "PASS" "${service_name} runtime health" "${service_health_detail}"

    if [ -n "${n_restarts}" ] && [ "${n_restarts}" -gt 0 ] 2>/dev/null; then
        add_check "systemd" "WARN" "WARN" "${service_name} restart count" "${n_restarts}"
    else
        add_check "systemd" "WARN" "PASS" "${service_name} restart count" "${n_restarts:-0}"
    fi
}

check_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        add_check "systemd" "WARN" "WARN" "systemctl available" "Command not available"
        return
    fi
    check_systemd_service "cnc-usb.service"
    check_systemd_service "cnc-webui.service"
    check_systemd_service "cnc-led.service"
}

read_runtime_lun_path() {
    local configfs_lun_file="/sys/kernel/config/usb_gadget/g1/functions/mass_storage.0/lun.0/file"
    local legacy_lun_file="/sys/module/g_mass_storage/parameters/file"
    local runtime_path=""

    if [ -r "${configfs_lun_file}" ]; then
        runtime_path="$(tr -d '\r\n' < "${configfs_lun_file}" 2>/dev/null || true)"
        runtime_path="$(trim_string "${runtime_path}")"
        if [ -n "${runtime_path}" ]; then
            printf '%s' "${runtime_path}"
            return 0
        fi
    fi

    if [ -r "${legacy_lun_file}" ]; then
        runtime_path="$(tr -d '\r\n' < "${legacy_lun_file}" 2>/dev/null || true)"
        runtime_path="$(trim_string "${runtime_path}")"
        if [ -n "${runtime_path}" ]; then
            printf '%s' "${runtime_path}"
            return 0
        fi
    fi

    return 1
}

check_runtime_consistency() {
    local expected_path=""
    local expected_slot=""
    local slot_file=""
    local image_a=""
    local image_b=""
    local runtime_path=""
    local expected_norm=""
    local runtime_norm=""

    if [ ! -f "${ENV_FILE}" ]; then
        add_check "runtime" "CRITICAL" "FAIL" "Runtime config file present" "Missing ${ENV_FILE}"
        return
    fi

    if is_shadow_enabled; then
        slot_file="$(get_env_value_or_default "${ENV_FILE}" "CNC_ACTIVE_SLOT_FILE" "/var/lib/cnc-control/shadow_active_slot.state")"
        image_a="$(get_env_value_or_default "${ENV_FILE}" "CNC_USB_IMG_A" "/var/lib/cnc-control/cnc_usb_a.img")"
        image_b="$(get_env_value_or_default "${ENV_FILE}" "CNC_USB_IMG_B" "/var/lib/cnc-control/cnc_usb_b.img")"

        if [ ! -f "${slot_file}" ]; then
            add_check "runtime" "CRITICAL" "FAIL" "Runtime active slot file present" "Missing file: ${slot_file}"
            return
        fi

        expected_slot="$(tr -d '\r\n\t ' < "${slot_file}" 2>/dev/null || true)"
        expected_slot="$(printf '%s' "${expected_slot}" | tr '[:lower:]' '[:upper:]')"
        if [ "${expected_slot}" = "A" ]; then
            expected_path="${image_a}"
        elif [ "${expected_slot}" = "B" ]; then
            expected_path="${image_b}"
        else
            add_check "runtime" "CRITICAL" "FAIL" "Runtime active slot valid" "${slot_file}: invalid value '${expected_slot}'"
            return
        fi
        add_check "runtime" "CRITICAL" "PASS" "Runtime active slot valid" "${slot_file}: ${expected_slot}"
    else
        expected_path="$(get_env_value "${ENV_FILE}" "CNC_USB_IMG" 2>/dev/null || true)"
        expected_path="$(trim_string "${expected_path}")"
        if [ -z "${expected_path}" ]; then
            add_check "runtime" "CRITICAL" "FAIL" "Runtime expected image path configured" "CNC_USB_IMG missing in ${ENV_FILE}"
            return
        fi
    fi

    runtime_path="$(read_runtime_lun_path || true)"
    runtime_path="$(trim_string "${runtime_path}")"
    if [ -z "${runtime_path}" ]; then
        add_check "runtime" "CRITICAL" "FAIL" "Runtime LUN image path detected" "Cannot read active LUN path from configfs or g_mass_storage"
        return
    fi

    add_check "runtime" "CRITICAL" "PASS" "Runtime LUN image path detected" "${runtime_path}"

    expected_norm="$(normalize_path "${expected_path}")"
    runtime_norm="$(normalize_path "${runtime_path}")"
    if [ "${runtime_norm}" = "${expected_norm}" ]; then
        add_check "runtime" "CRITICAL" "PASS" "Runtime LUN image matches expected" "runtime=${runtime_norm}; expected=${expected_norm}"
    else
        add_check "runtime" "CRITICAL" "FAIL" "Runtime LUN image matches expected" "runtime=${runtime_norm}; expected=${expected_norm}"
    fi
}

check_recent_journal_errors() {
    local scope_label="$1"
    local output=""
    local rc=0
    local compact=""

    shift
    output="$(journalctl --no-pager -n 20 -p 3 "$@" 2>&1)"
    rc=$?
    compact="$(compact_output "${output}")"

    if [ "${rc}" -ne 0 ]; then
        if printf '%s' "${compact}" | grep -Eiq 'access denied|permission denied|not permitted'; then
            add_check "logs" "WARN" "WARN" "${scope_label} journal access" "${compact}"
        else
            add_check "logs" "WARN" "WARN" "${scope_label} journal access" "journalctl rc=${rc}; ${compact}"
        fi
        return
    fi

    if [ -z "${compact}" ] || printf '%s' "${compact}" | grep -q "No entries"; then
        add_check "logs" "CRITICAL" "PASS" "${scope_label} journal errors (last 20)" "none"
    else
        add_check "logs" "CRITICAL" "FAIL" "${scope_label} journal errors (last 20)" "${compact}"
    fi
}

check_system_cnc_journal_errors() {
    local output=""
    local rc=0
    local filtered=""
    local compact=""
    local cnc_pattern='cnc[-_]|cnc-control|shadow|shadow_usb_export|led_status|webui'

    output="$(journalctl --no-pager -n 200 -p 3 2>&1)"
    rc=$?
    if [ "${rc}" -ne 0 ]; then
        compact="$(compact_output "${output}")"
        if printf '%s' "${compact}" | grep -Eiq 'access denied|permission denied|not permitted'; then
            add_check "logs" "WARN" "WARN" "System journal access" "${compact}"
        else
            add_check "logs" "WARN" "WARN" "System journal access" "journalctl rc=${rc}; ${compact}"
        fi
        return
    fi

    filtered="$(printf '%s\n' "${output}" | grep -Eai "${cnc_pattern}" || true)"
    compact="$(compact_output "${filtered}")"
    if [ -z "${compact}" ]; then
        add_check "logs" "CRITICAL" "PASS" "System CNC journal errors (last 200)" "none"
    else
        add_check "logs" "CRITICAL" "FAIL" "System CNC journal errors (last 200)" "${compact}"
    fi
}

check_logs() {
    if ! command_available "journalctl"; then
        add_check "logs" "WARN" "WARN" "journalctl available" "Command not available"
        return
    fi

    check_system_cnc_journal_errors
    check_recent_journal_errors "cnc-usb.service" -u "cnc-usb.service"
    check_recent_journal_errors "cnc-webui.service" -u "cnc-webui.service"
    check_recent_journal_errors "cnc-led.service" -u "cnc-led.service"
}

check_hardware() {
    local model=""
    local throttled_output=""
    local throttled_value=""

    if [ -r "/proc/device-tree/model" ]; then
        model="$(tr -d '\0' < "/proc/device-tree/model" 2>/dev/null || true)"
        model="$(trim_string "${model}")"
        if [ -n "${model}" ]; then
            add_check "hardware" "WARN" "PASS" "Hardware model detected" "${model}"
        else
            add_check "hardware" "WARN" "WARN" "Hardware model detected" "Empty /proc/device-tree/model"
        fi
    else
        add_check "hardware" "WARN" "WARN" "Hardware model detected" "/proc/device-tree/model not accessible"
    fi

    if ! command -v vcgencmd >/dev/null 2>&1; then
        add_check "hardware" "WARN" "WARN" "vcgencmd get_throttled" "Command vcgencmd not available"
        return
    fi

    throttled_output="$(vcgencmd get_throttled 2>&1 || true)"
    throttled_output="$(trim_string "${throttled_output}")"
    throttled_value="${throttled_output#*=}"
    throttled_value="$(trim_string "${throttled_value}")"

    if [ -z "${throttled_value}" ] || [ "${throttled_output}" = "${throttled_value}" ]; then
        add_check "hardware" "WARN" "WARN" "vcgencmd get_throttled" "${throttled_output}"
    elif [ "${throttled_value}" = "0x0" ] || [ "${throttled_value}" = "0" ]; then
        add_check "hardware" "WARN" "PASS" "Voltage throttling detected" "${throttled_output}"
    else
        add_check "hardware" "WARN" "WARN" "Voltage throttling detected" "${throttled_output}"
    fi
}

print_text_report() {
    local i=0
    local status_label="OK"

    if [ "${CRITICAL_COUNT}" -gt 0 ]; then
        status_label="FAILED"
    fi

    echo "=============================="
    echo " CNC SELFTEST (PRO)"
    echo "=============================="
    echo ""

    for i in "${!REPORT_STATUS[@]}"; do
        printf '[%s] %s\n' "${REPORT_STATUS[$i]}" "${REPORT_MESSAGE[$i]}"
        if [ "${VERBOSE}" -eq 1 ] && [ -n "${REPORT_DETAIL[$i]}" ]; then
            printf '       %s\n' "${REPORT_DETAIL[$i]}"
        fi
    done

    echo ""
    echo "--------------------------------"
    echo "CRITICAL: ${CRITICAL_COUNT}"
    echo "WARNINGS: ${WARN_COUNT}"
    echo "--------------------------------"
    echo "RESULT: ${status_label}"
}

print_json_report() {
    local i=0
    local summary_status="OK"

    if [ "${CRITICAL_COUNT}" -gt 0 ]; then
        summary_status="FAILED"
    fi

    printf '{\n'
    for i in "${!SECTIONS[@]}"; do
        if [ "${i}" -gt 0 ]; then
            printf ',\n'
        fi
        printf '  "%s": {\n' "${SECTIONS[$i]}"
        printf '    "status": "%s",\n' "${SECTION_STATUS[$i]}"
        printf '    "checks": ['
        printf '%s' "${SECTION_CHECKS_JSON[$i]}"
        printf ']\n'
        printf '  }'
    done
    printf ',\n'
    printf '  "summary": {\n'
    printf '    "critical": %s,\n' "${CRITICAL_COUNT}"
    printf '    "warnings": %s,\n' "${WARN_COUNT}"
    printf '    "status": "%s"\n' "${summary_status}"
    printf '  }\n'
    printf '}\n'
}

usage() {
    cat <<'EOF'
Uzycie:
  cnc_selftest
  cnc_selftest --verbose
  cnc_selftest --json
EOF
}

parse_args() {
    local arg=""
    for arg in "$@"; do
        case "${arg}" in
            --verbose) VERBOSE=1 ;;
            --json) JSON_ONLY=1 ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                echo "Nieznana opcja: ${arg}" >&2
                usage >&2
                exit 1
                ;;
        esac
    done
}

compute_exit_code() {
    if [ "${CRITICAL_COUNT}" -gt 0 ]; then
        return 1
    fi
    if [ "${WARN_COUNT}" -gt 0 ]; then
        return 2
    fi
    return 0
}

main() {
    parse_args "$@"
    init_sections

    check_boot
    check_kernel
    check_gadget
    check_usb_image
    check_project_config
    check_shadow
    check_samba
    check_systemd
    check_runtime_consistency
    check_logs
    check_hardware

    if [ "${JSON_ONLY}" -eq 1 ]; then
        print_json_report
    else
        print_text_report
    fi

    compute_exit_code
    return $?
}

main "$@"
