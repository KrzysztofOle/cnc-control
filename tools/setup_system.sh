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

mkdir -p /etc/cnc-control /var/lib/cnc-control /mnt/cnc_usb

if [ ! -f "${ENV_DEST}" ]; then
    install -o root -g root -m 644 "${ENV_SRC}" "${ENV_DEST}"
fi

chown root:root "${ENV_DEST}"
chmod 644 "${ENV_DEST}"

chown root:root /var/lib/cnc-control
chmod 755 /mnt/cnc_usb

install -o root -g root -m 644 "${SYSTEMD_SERVICE_SRC}" "${SYSTEMD_SERVICE_DEST}"

mkdir -p "${OVERRIDE_DIR}"
cat <<'OVERRIDE' > "${OVERRIDE_FILE}"
[Service]
EnvironmentFile=/etc/cnc-control/cnc-control.env
OVERRIDE

systemctl daemon-reload

echo "Gotowe. Unit zainstalowany: ${SYSTEMD_SERVICE_DEST}"
