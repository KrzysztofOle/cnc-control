#!/bin/bash
set -u
set -o pipefail

VERBOSE=0
JSON_ONLY=0
CRITICAL_COUNT=0
WARN_COUNT=0

ENV_FILE="/etc/cnc-control/cnc-control.env"
MIN_USB_IMAGE_SIZE_BYTES=1048576

SECTIONS=("boot" "kernel" "gadget" "usb_image" "project_config" "systemd" "hardware")

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
        systemd) printf '5' ;;
        hardware) printf '6' ;;
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

    if ! command -v file >/dev/null 2>&1; then
        add_check "usb_image" "CRITICAL" "FAIL" "USB image FAT type" "Command 'file' not available"
    else
        file_info="$(file -b "${image_path}" 2>/dev/null || true)"
        if printf '%s' "${file_info}" | grep -Eiq 'fat'; then
            add_check "usb_image" "CRITICAL" "PASS" "USB image FAT type" "${file_info}"
        else
            add_check "usb_image" "CRITICAL" "FAIL" "USB image FAT type" "${file_info}"
        fi
    fi

    if ! command -v fsck.vfat >/dev/null 2>&1; then
        add_check "usb_image" "WARN" "WARN" "USB image fsck check" "Command fsck.vfat not available"
        return
    fi

    fsck_output="$(fsck.vfat -n "${image_path}" 2>&1)"
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

check_systemd_service() {
    local service_name="$1"
    local enabled_output=""
    local active_output=""

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
}

check_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        add_check "systemd" "WARN" "WARN" "systemctl available" "Command not available"
        return
    fi
    check_systemd_service "cnc-usb.service"
    check_systemd_service "cnc-webui.service"
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
    check_systemd
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
