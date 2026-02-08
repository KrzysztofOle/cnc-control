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

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

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
    for pkg in hostapd dnsmasq; do
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

mkdir -p /etc/cnc-control /var/lib/cnc-control "${SAMBA_SHARE_PATH}"

if [ ! -f "${ENV_DEST}" ]; then
    install -o root -g root -m 644 "${ENV_SRC}" "${ENV_DEST}"
fi

chown root:root "${ENV_DEST}"
chmod 644 "${ENV_DEST}"

chown root:root /var/lib/cnc-control "${SAMBA_SHARE_PATH}"
chmod 755 "${SAMBA_SHARE_PATH}"

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

echo "Gotowe. Unit zainstalowany: ${SYSTEMD_SERVICE_DEST}"
