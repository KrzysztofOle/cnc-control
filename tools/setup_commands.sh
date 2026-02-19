#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMMANDS=("usb_mode" "net_mode" "status")
SCRIPTS=("usb_mode.sh" "net_mode.sh" "status.sh")

TARGET_DIR=""
USE_SUDO="false"
CURRENT_USER="${SUDO_USER:-$USER}"
CURRENT_HOME="$(getent passwd "${CURRENT_USER}" | cut -d: -f6 2>/dev/null || true)"

if [ -z "${CURRENT_HOME}" ]; then
    CURRENT_HOME="${HOME}"
fi

if [ -w "/usr/local/bin" ]; then
    TARGET_DIR="/usr/local/bin"
elif command -v sudo >/dev/null 2>&1; then
    TARGET_DIR="/usr/local/bin"
    USE_SUDO="true"
else
    TARGET_DIR="${CURRENT_HOME}/.local/bin"
fi

if [ "${USE_SUDO}" = "true" ]; then
    sudo mkdir -p "${TARGET_DIR}"
else
    mkdir -p "${TARGET_DIR}"
fi

for i in "${!COMMANDS[@]}"; do
    cmd="${COMMANDS[$i]}"
    script="${REPO_ROOT}/${SCRIPTS[$i]}"

    if [ ! -f "${script}" ]; then
        echo "Brak pliku: ${script}"
        exit 1
    fi

    if [ "${USE_SUDO}" = "true" ]; then
        sudo ln -sfn "${script}" "${TARGET_DIR}/${cmd}"
    else
        ln -sfn "${script}" "${TARGET_DIR}/${cmd}"
    fi
done

if [ "${TARGET_DIR}" = "${CURRENT_HOME}/.local/bin" ]; then
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    RC_FILES=("${CURRENT_HOME}/.bashrc" "${CURRENT_HOME}/.zshrc")
    for rc_file in "${RC_FILES[@]}"; do
        if [ ! -f "${rc_file}" ]; then
            continue
        fi
        if ! grep -qF "${PATH_LINE}" "${rc_file}" 2>/dev/null; then
            echo "" >> "${rc_file}"
            echo "# CNC Control CLI" >> "${rc_file}"
            echo "${PATH_LINE}" >> "${rc_file}"
            echo "Dodano PATH do ${rc_file}. Uruchom: source ${rc_file}"
        fi
    done

    if [ ! -f "${CURRENT_HOME}/.bashrc" ] && [ ! -f "${CURRENT_HOME}/.zshrc" ]; then
        BASHRC="${CURRENT_HOME}/.bashrc"
        echo "" >> "${BASHRC}"
        echo "# CNC Control CLI" >> "${BASHRC}"
        echo "${PATH_LINE}" >> "${BASHRC}"
        echo "Dodano PATH do ${BASHRC}. Uruchom: source ${BASHRC}"
    fi
fi

echo "Gotowe. Komendy dostepne: usb_mode, net_mode, status"
