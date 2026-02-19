#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/KrzysztofOle/cnc-control.git"
PREFERRED_USER_DEFAULT="andrzej"
APT_PACKAGES=(
    git
    python3
    python3-venv
    python3-pip
    python3-flask
    python3-werkzeug
    python3-rpi-ws281x
    network-manager
    openssh-server
    curl
    samba
)

run_as_root() {
    if [ "${EUID}" -eq 0 ]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "Brak uprawnien root i brak sudo."
        exit 1
    fi
}

resolve_default_user() {
    if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
        printf '%s\n' "${SUDO_USER}"
        return
    fi

    current_user="$(id -un)"
    if [ "${current_user}" != "root" ]; then
        printf '%s\n' "${current_user}"
        return
    fi

    if id -u "${PREFERRED_USER_DEFAULT}" >/dev/null 2>&1; then
        printf '%s\n' "${PREFERRED_USER_DEFAULT}"
        return
    fi

    regular_user="$(getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody" {print $1; exit}')"
    if [ -n "${regular_user}" ]; then
        printf '%s\n' "${regular_user}"
        return
    fi

    echo "Nie znaleziono automatycznie docelowego uzytkownika."
    echo "Ustaw recznie: CNC_INSTALL_USER=<user> ./tools/bootstrap_cnc.sh"
    exit 1
}

resolve_install_user() {
    if [ -n "${CNC_INSTALL_USER:-}" ]; then
        printf '%s\n' "${CNC_INSTALL_USER}"
        return
    fi

    resolve_default_user
}

run_as_install_user() {
    if [ "$(id -un)" = "${INSTALL_USER}" ]; then
        "$@"
        return
    fi

    if [ "${EUID}" -eq 0 ]; then
        if command -v runuser >/dev/null 2>&1; then
            runuser -u "${INSTALL_USER}" -- "$@"
            return
        fi
        echo "Brak runuser. Nie moge uruchomic polecenia jako ${INSTALL_USER}."
        exit 1
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo -u "${INSTALL_USER}" "$@"
        return
    fi

    echo "Nie mozna uruchomic polecenia jako ${INSTALL_USER} (brak sudo)."
    exit 1
}

echo "=== CNC Bootstrap Start ==="

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Ten skrypt wymaga apt-get (Debian/Raspberry Pi OS)."
    exit 1
fi

INSTALL_USER="$(resolve_install_user)"
if ! id -u "${INSTALL_USER}" >/dev/null 2>&1; then
    echo "Nie znaleziono uzytkownika docelowego: ${INSTALL_USER}"
    exit 1
fi

INSTALL_HOME="$(getent passwd "${INSTALL_USER}" | cut -d: -f6)"
if [ -z "${INSTALL_HOME}" ]; then
    echo "Nie moge ustalic katalogu domowego dla ${INSTALL_USER}."
    exit 1
fi

REPO_URL="${CNC_REPO_URL:-${REPO_URL_DEFAULT}}"
REPO_DIR="${CNC_REPO_DIR:-${INSTALL_HOME}/cnc-control}"

echo "[1/7] Aktualizacja systemu"
run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

echo "[2/7] Instalacja pakietow"
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"

echo "[3/7] Uruchamianie uslug bazowych"
run_as_root systemctl enable --now ssh
run_as_root systemctl enable --now NetworkManager

echo "[4/7] Klonowanie lub aktualizacja repozytorium (${REPO_URL})"
run_as_install_user mkdir -p "$(dirname "${REPO_DIR}")"
if [ -d "${REPO_DIR}/.git" ]; then
    run_as_install_user git -C "${REPO_DIR}" remote set-url origin "${REPO_URL}"
    run_as_install_user git -C "${REPO_DIR}" fetch --all --prune
    run_as_install_user git -C "${REPO_DIR}" pull --ff-only
elif [ -d "${REPO_DIR}" ] && [ -n "$(ls -A "${REPO_DIR}")" ]; then
    echo "Katalog ${REPO_DIR} istnieje i nie jest repozytorium git. Przerwano."
    exit 1
else
    run_as_install_user git clone "${REPO_URL}" "${REPO_DIR}"
fi

echo "[5/7] Instalacja konfiguracji systemowej cnc-control"
run_as_root bash "${REPO_DIR}/tools/setup_system.sh"

echo "[6/7] Instalacja skrotow CLI"
run_as_root bash "${REPO_DIR}/tools/setup_commands.sh"

echo "[7/7] Instalacja uslug systemd (WebUI + USB + LED)"
run_as_root env SUDO_USER="${INSTALL_USER}" bash "${REPO_DIR}/tools/setup_webui.sh" "${REPO_DIR}"
run_as_root bash "${REPO_DIR}/tools/setup_usb_service.sh" "${REPO_DIR}"
run_as_root bash "${REPO_DIR}/tools/setup_led_service.sh" "${REPO_DIR}"

echo "=== CNC Bootstrap Done ==="
echo "Repozytorium: ${REPO_DIR}"
echo "Uzytkownik uslug: ${INSTALL_USER}"
echo "Sprawdz: systemctl status cnc-webui cnc-usb cnc-led"
