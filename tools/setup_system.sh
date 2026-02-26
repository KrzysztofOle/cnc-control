#!/bin/bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
    echo "Ten skrypt musi byc uruchomiony jako root (sudo)."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SYSTEMD_SERVICE_SRC="${REPO_ROOT}/systemd/cnc-webui.service"
SYSTEMD_SERVICE_DEST="/etc/systemd/system/cnc-webui.service"
SYSTEMD_AP_SERVICE_SRC="${REPO_ROOT}/systemd/cnc-ap.service"
SYSTEMD_AP_SERVICE_DEST="/etc/systemd/system/cnc-ap.service"
SYSTEMD_WIFI_FALLBACK_SRC="${REPO_ROOT}/systemd/cnc-wifi-fallback.service"
SYSTEMD_WIFI_FALLBACK_DEST="/etc/systemd/system/cnc-wifi-fallback.service"
WIFI_FALLBACK_SCRIPT="${REPO_ROOT}/tools/wifi_fallback.sh"
POLKIT_RULE_SRC="${REPO_ROOT}/systemd/polkit/50-cnc-webui-restart.rules"
POLKIT_RULE_DEST="/etc/polkit-1/rules.d/50-cnc-webui-restart.rules"
ENV_SRC="${REPO_ROOT}/config/cnc-control.env.example"
ENV_DEST="/etc/cnc-control/cnc-control.env"
AP_CONFIG_SRC_DIR="${REPO_ROOT}/config/ap"
HOSTAPD_CONF_SRC="${AP_CONFIG_SRC_DIR}/hostapd.conf"
DNSMASQ_CONF_SRC="${AP_CONFIG_SRC_DIR}/dnsmasq.conf"
AP_CONFIG_DEST_DIR="/etc/cnc-control/ap"
HOSTAPD_CONF_DEST="${AP_CONFIG_DEST_DIR}/hostapd.conf"
DNSMASQ_CONF_DEST="${AP_CONFIG_DEST_DIR}/dnsmasq.conf"
OVERRIDE_DIR="/etc/systemd/system/cnc-webui.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
SAMBA_CONF="/etc/samba/smb.conf"
SAMBA_SHARE_NAME="cnc_usb"
SAMBA_SHARE_PATH="/mnt/cnc_usb"
CLOUD_INIT_UNITS=(
    cloud-init-local.service
    cloud-init.service
    cloud-config.service
    cloud-init-network.service
)
DWC2_OVERLAY_LINE="dtoverlay=dwc2,dr_mode=peripheral"
USB_OTG_CHANGED=0

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

resolve_boot_file() {
    local primary="$1"
    local fallback="$2"

    if [ -f "${primary}" ]; then
        echo "${primary}"
        return 0
    fi

    if [ -f "${fallback}" ]; then
        echo "${fallback}"
        return 0
    fi

    return 1
}

resolve_active_boot_file() {
    local preferred="$1"
    local fallback="$2"
    local candidate=""
    local mount_dir=""

    for candidate in "${preferred}" "${fallback}"; do
        if [ ! -f "${candidate}" ]; then
            continue
        fi
        mount_dir="$(dirname "${candidate}")"
        if awk -v p="${mount_dir}" '$2 == p { found=1 } END { exit !found }' /proc/mounts 2>/dev/null; then
            echo "${candidate}"
            return 0
        fi
    done

    resolve_boot_file "${preferred}" "${fallback}"
}

ensure_backup_file() {
    local src="$1"
    local backup="$2"

    if [ ! -f "${backup}" ]; then
        cp -a "${src}" "${backup}"
        echo "[INFO] Utworzono kopie zapasowa: ${backup}"
    fi
}

upsert_env_var() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    local escaped_value=""

    escaped_value="$(printf '%s' "${value}" | sed -e 's/[\/&]/\\&/g')"

    if grep -qE "^[[:space:]]*${key}=" "${env_file}"; then
        sed -i -E "s|^[[:space:]]*${key}=.*$|${key}=${escaped_value}|" "${env_file}"
    else
        printf '\n%s=%s\n' "${key}" "${value}" >> "${env_file}"
    fi
}

has_dwc2_overlay_in_all_section() {
    local config_file="$1"

    awk '
        BEGIN { in_all = 0; found = 0 }
        /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
            if ($0 ~ /^[[:space:]]*\[all\][[:space:]]*$/) {
                in_all = 1
            } else {
                in_all = 0
            }
        }
        in_all && $0 ~ /^[[:space:]]*dtoverlay=dwc2,dr_mode=peripheral([[:space:]]*#.*)?[[:space:]]*$/ {
            found = 1
        }
        END { exit(found ? 0 : 1) }
    ' "${config_file}"
}

configure_usb_otg_dwc2() {
    local config_file cmdline_file
    local tmp_file normalized_cmdline
    local cfg_candidate
    local config_candidates=("/boot/firmware/config.txt" "/boot/config.txt")

    config_file="$(resolve_active_boot_file "/boot/firmware/config.txt" "/boot/config.txt")" || {
        echo "Brak pliku config.txt w /boot ani /boot/firmware."
        exit 1
    }
    cmdline_file="$(resolve_active_boot_file "/boot/firmware/cmdline.txt" "/boot/cmdline.txt")" || {
        echo "Brak pliku cmdline.txt w /boot ani /boot/firmware."
        exit 1
    }

    for cfg_candidate in "${config_candidates[@]}"; do
        if [ ! -f "${cfg_candidate}" ]; then
            continue
        fi

        tmp_file="$(mktemp)"
        awk -v overlay_line="${DWC2_OVERLAY_LINE}" '
            BEGIN { inserted = 0; saw_all = 0 }
            {
                if ($0 ~ /^[[:space:]]*#?[[:space:]]*dtoverlay=dwc2([[:space:]]*,[^#[:space:]]*)?([[:space:]]*#.*)?[[:space:]]*$/) {
                    next
                }

                if ($0 ~ /^[[:space:]]*\[all\][[:space:]]*$/) {
                    saw_all = 1
                    print
                    if (inserted == 0) {
                        print overlay_line
                        inserted = 1
                    }
                    next
                }

                print
            }
            END {
                if (inserted == 0) {
                    if (saw_all == 0) {
                        print "[all]"
                    }
                    print overlay_line
                }
            }
        ' "${cfg_candidate}" > "${tmp_file}"

        if ! cmp -s "${cfg_candidate}" "${tmp_file}"; then
            ensure_backup_file "${cfg_candidate}" "${cfg_candidate}.bak"
            cp "${tmp_file}" "${cfg_candidate}"
            USB_OTG_CHANGED=1
        fi
        rm -f "${tmp_file}"
    done

    normalized_cmdline="$(tr '\n' ' ' < "${cmdline_file}" | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')"
    if [ -z "${normalized_cmdline}" ]; then
        echo "Plik ${cmdline_file} jest pusty."
        exit 1
    fi
    if [[ "${normalized_cmdline}" != *"modules-load=dwc2"* ]]; then
        normalized_cmdline="${normalized_cmdline} modules-load=dwc2"
    fi

    tmp_file="$(mktemp)"
    printf '%s\n' "${normalized_cmdline}" > "${tmp_file}"
    if ! cmp -s "${cmdline_file}" "${tmp_file}"; then
        ensure_backup_file "${cmdline_file}" "${cmdline_file}.bak"
        cp "${tmp_file}" "${cmdline_file}"
        USB_OTG_CHANGED=1
    fi
    rm -f "${tmp_file}"

    echo "[INFO] Walidacja USB OTG (dwc2)"
    if has_dwc2_overlay_in_all_section "${config_file}"; then
        echo " - dtoverlay=dwc2,dr_mode=peripheral aktywne: TAK"
    else
        echo " - dtoverlay=dwc2,dr_mode=peripheral aktywne: NIE"
    fi

    if grep -Eq '(^|[[:space:]])modules-load=dwc2([[:space:]]|,|$)' "${cmdline_file}"; then
        echo " - modules-load=dwc2 obecne: TAK"
    else
        echo " - modules-load=dwc2 obecne: NIE"
    fi
}

create_usb_image_if_missing() {
    local image_path="${CNC_USB_IMG:-}"
    local size_mb="${CNC_USB_IMG_SIZE_MB:-1024}"

    if [ -z "${image_path}" ]; then
        echo "[WARN] Brak CNC_USB_IMG w ${ENV_DEST}. Pomijam tworzenie obrazu USB."
        return 0
    fi

    if [ -e "${image_path}" ] && [ ! -f "${image_path}" ]; then
        echo "Sciezka CNC_USB_IMG nie wskazuje na zwykly plik: ${image_path}"
        exit 1
    fi

    if [ -f "${image_path}" ] && [ -s "${image_path}" ]; then
        return 0
    fi

    if ! [[ "${size_mb}" =~ ^[1-9][0-9]*$ ]]; then
        echo "Nieprawidlowa wartosc CNC_USB_IMG_SIZE_MB: ${size_mb}"
        exit 1
    fi

    if ! command -v mkfs.vfat >/dev/null 2>&1; then
        echo "Brak mkfs.vfat. Zainstaluj pakiet dosfstools."
        exit 1
    fi

    mkdir -p "$(dirname "${image_path}")"
    truncate -s "${size_mb}M" "${image_path}"
    mkfs.vfat -F 32 "${image_path}" >/dev/null
    chmod 664 "${image_path}"
    echo "[INFO] Utworzono obraz USB: ${image_path} (${size_mb}MB)"
}

if [ ! -f "${SYSTEMD_SERVICE_SRC}" ]; then
    echo "Brak pliku unita: ${SYSTEMD_SERVICE_SRC}"
    exit 1
fi

if [ ! -f "${SYSTEMD_AP_SERVICE_SRC}" ]; then
    echo "Brak pliku unita: ${SYSTEMD_AP_SERVICE_SRC}"
    exit 1
fi

if [ ! -f "${SYSTEMD_WIFI_FALLBACK_SRC}" ]; then
    echo "Brak pliku unita: ${SYSTEMD_WIFI_FALLBACK_SRC}"
    exit 1
fi

if [ ! -f "${ENV_SRC}" ]; then
    echo "Brak pliku konfiguracyjnego: ${ENV_SRC}"
    exit 1
fi

if [ ! -f "${WIFI_FALLBACK_SCRIPT}" ]; then
    echo "Brak skryptu: ${WIFI_FALLBACK_SCRIPT}"
    exit 1
fi

if [ ! -f "${HOSTAPD_CONF_SRC}" ]; then
    echo "Brak pliku konfiguracyjnego: ${HOSTAPD_CONF_SRC}"
    exit 1
fi

if [ ! -f "${DNSMASQ_CONF_SRC}" ]; then
    echo "Brak pliku konfiguracyjnego: ${DNSMASQ_CONF_SRC}"
    exit 1
fi

if command -v dpkg >/dev/null 2>&1; then
    missing_pkgs=()
    for pkg in hostapd dnsmasq dosfstools; do
        if ! dpkg -s "${pkg}" >/dev/null 2>&1; then
            missing_pkgs+=("${pkg}")
        fi
    done
    if [ "${#missing_pkgs[@]}" -gt 0 ]; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "[INFO] Instalacja pakietow: ${missing_pkgs[*]}"
            apt-get update
            DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_pkgs[@]}"
        else
            echo "Brak apt-get. Zainstaluj pakiety recznie: ${missing_pkgs[*]}"
            exit 1
        fi
    fi
else
    echo "Brak dpkg. Pomijam sprawdzanie hostapd/dnsmasq."
fi

configure_usb_otg_dwc2

mkdir -p /etc/cnc-control /var/lib/cnc-control "${SAMBA_SHARE_PATH}"

if [ ! -f "${ENV_DEST}" ]; then
    install -o root -g root -m 644 "${ENV_SRC}" "${ENV_DEST}"
fi

chown root:root "${ENV_DEST}"
chmod 644 "${ENV_DEST}"
upsert_env_var "${ENV_DEST}" "CNC_CONTROL_REPO" "${REPO_ROOT}"

# shellcheck source=/etc/cnc-control/cnc-control.env
set -a
source "${ENV_DEST}"
set +a

chown root:root /var/lib/cnc-control
chmod 755 /var/lib/cnc-control

create_usb_image_if_missing

if mountpoint -q "${SAMBA_SHARE_PATH}"; then
    echo "[INFO] ${SAMBA_SHARE_PATH} jest zamontowany – pomijam chown"
else
    chown root:root "${SAMBA_SHARE_PATH}"
    chmod 755 "${SAMBA_SHARE_PATH}"
fi

install -o root -g root -m 644 "${SYSTEMD_SERVICE_SRC}" "${SYSTEMD_SERVICE_DEST}"
install -o root -g root -m 644 "${SYSTEMD_AP_SERVICE_SRC}" "${SYSTEMD_AP_SERVICE_DEST}"
install -o root -g root -m 644 "${SYSTEMD_WIFI_FALLBACK_SRC}" "${SYSTEMD_WIFI_FALLBACK_DEST}"

chmod 755 "${WIFI_FALLBACK_SCRIPT}"

mkdir -p "${AP_CONFIG_DEST_DIR}"
if [ ! -f "${HOSTAPD_CONF_DEST}" ]; then
    install -o root -g root -m 644 "${HOSTAPD_CONF_SRC}" "${HOSTAPD_CONF_DEST}"
fi
if [ ! -f "${DNSMASQ_CONF_DEST}" ]; then
    install -o root -g root -m 644 "${DNSMASQ_CONF_SRC}" "${DNSMASQ_CONF_DEST}"
fi

if [ -f "${POLKIT_RULE_SRC}" ]; then
    mkdir -p "$(dirname "${POLKIT_RULE_DEST}")"
    install -o root -g root -m 644 "${POLKIT_RULE_SRC}" "${POLKIT_RULE_DEST}"
else
    echo "Brak pliku PolicyKit: ${POLKIT_RULE_SRC}"
fi

mkdir -p "${OVERRIDE_DIR}"
cat <<'OVERRIDE' > "${OVERRIDE_FILE}"
[Service]
EnvironmentFile=/etc/cnc-control/cnc-control.env
OVERRIDE

systemctl daemon-reload

# W trybie fallback uruchamiamy hostapd/dnsmasq tylko na zyczenie.
echo "[INFO] Wylaczanie domyslnych uslug hostapd/dnsmasq"
for svc in hostapd.service dnsmasq.service; do
    if systemctl list-unit-files --type=service | grep -q "^${svc}"; then
        systemctl disable --now "${svc}" || true
    else
        echo "[INFO] Pomijam brakujaca usluge: ${svc}"
    fi
done

systemctl enable cnc-wifi-fallback.service

# Raspberry Pi jako appliance CNC: cloud-init jest zbedny i spowalnia start.
echo "[INFO] Wylaczanie cloud-init (uslugi i maskowanie)"
for unit in "${CLOUD_INIT_UNITS[@]}"; do
    if systemctl list-unit-files --type=service | grep -q "^${unit}"; then
        echo "[INFO] Disabling ${unit}"
        systemctl disable --now "${unit}" || true
        echo "[INFO] Masking ${unit}"
        systemctl mask "${unit}" || true
    else
        echo "[INFO] Pomijam brakujaca usluge: ${unit}"
    fi
done

echo "[INFO] Tworzenie /etc/cloud/cloud-init.disabled"
mkdir -p /etc/cloud
touch /etc/cloud/cloud-init.disabled

# Siec jest wymagana (SSH, WebUI, Samba), ale nie moze blokowac startu systemu.
echo "[INFO] Disabling NetworkManager-wait-online.service"
systemctl disable --now NetworkManager-wait-online.service || true
echo "[INFO] Masking NetworkManager-wait-online.service"
systemctl mask NetworkManager-wait-online.service || true

if command -v smbd >/dev/null 2>&1; then
    if [ -f "${SAMBA_CONF}" ]; then
        backup="/etc/samba/smb.conf.cnc-control.$(date +%Y%m%d%H%M%S).bak"
        cp -a "${SAMBA_CONF}" "${backup}"
        echo "Utworzono kopie: ${backup}"
    fi

    mkdir -p /etc/samba
    cat <<SMB > "${SAMBA_CONF}"
[global]
   server role = standalone server
   workgroup = WORKGROUP
   disable netbios = yes
   smb ports = 445
   server min protocol = SMB2
   server max protocol = SMB3
   map to guest = Bad User
   load printers = no
   printing = bsd
   printcap name = /dev/null
   log file = /var/log/samba/log.%m
   max log size = 1000
   logging = file

[${SAMBA_SHARE_NAME}]
   path = ${SAMBA_SHARE_PATH}
   browseable = yes
   read only = no
   guest ok = yes
   create mask = 0664
   directory mask = 0775
SMB

    if getent group sambashare >/dev/null 2>&1; then
        chgrp sambashare "${SAMBA_SHARE_PATH}"
        chmod 2775 "${SAMBA_SHARE_PATH}"
    else
        chmod 777 "${SAMBA_SHARE_PATH}"
    fi

    if systemctl list-unit-files --type=service | grep -q "^smbd.service"; then
        systemctl enable --now smbd.service
    fi
else
    echo "Samba (smbd) nie jest zainstalowana. Pomijam konfiguracje udostepniania."
fi

if systemctl list-unit-files --type=service | grep -q "^samba-ad-dc.service"; then
    systemctl disable --now samba-ad-dc.service
fi

if systemctl list-unit-files --type=service | grep -q "^nmbd.service"; then
    systemctl disable --now nmbd.service
fi

if [ "${USB_OTG_CHANGED}" -eq 1 ]; then
    echo "USB OTG (dwc2) skonfigurowane."
    echo "Wymagany restart systemu."
fi

echo "Gotowe. Unit zainstalowany: ${SYSTEMD_SERVICE_DEST}"
