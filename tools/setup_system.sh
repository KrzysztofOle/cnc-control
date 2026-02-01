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
ENV_SRC="${REPO_ROOT}/config/cnc-control.env.example"
ENV_DEST="/etc/cnc-control/cnc-control.env"
OVERRIDE_DIR="/etc/systemd/system/cnc-webui.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/override.conf"
SAMBA_CONF="/etc/samba/smb.conf"
SAMBA_SHARE_NAME="cnc_usb"
SAMBA_SHARE_PATH="/mnt/cnc_usb"
CLOUD_INIT_UNITS=(
    cloud-init-local.service
    cloud-init.service
    cloud-config.service
    cloud-final.service
    cloud-init.target
)

if ! command -v systemctl >/dev/null 2>&1; then
    echo "Brak systemd (systemctl)."
    exit 1
fi

if [ ! -f "${SYSTEMD_SERVICE_SRC}" ]; then
    echo "Brak pliku unita: ${SYSTEMD_SERVICE_SRC}"
    exit 1
fi

if [ ! -f "${ENV_SRC}" ]; then
    echo "Brak pliku konfiguracyjnego: ${ENV_SRC}"
    exit 1
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

mkdir -p "${OVERRIDE_DIR}"
cat <<'OVERRIDE' > "${OVERRIDE_FILE}"
[Service]
EnvironmentFile=/etc/cnc-control/cnc-control.env
OVERRIDE

systemctl daemon-reload
systemctl disable --now NetworkManager-wait-online.service
systemctl mask NetworkManager-wait-online.service

for unit in "${CLOUD_INIT_UNITS[@]}"; do
    if systemctl list-unit-files --type=service --type=target | grep -q "^${unit}"; then
        systemctl disable --now "${unit}"
        systemctl mask "${unit}"
    fi
done

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
