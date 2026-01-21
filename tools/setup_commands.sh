#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMMANDS=("usb_mode" "net_mode" "status")
SCRIPTS=("usb_mode.sh" "net_mode.sh" "status.sh")

TARGET_DIR=""
USE_SUDO="false"

if [ -w "/usr/local/bin" ]; then
    TARGET_DIR="/usr/local/bin"
elif command -v sudo >/dev/null 2>&1; then
    TARGET_DIR="/usr/local/bin"
    USE_SUDO="true"
else
    TARGET_DIR="${HOME}/.local/bin"
fi

mkdir -p "${TARGET_DIR}"

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

if [ "${TARGET_DIR}" = "${HOME}/.local/bin" ]; then
    BASHRC="${HOME}/.bashrc"
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
    if ! grep -qF "${PATH_LINE}" "${BASHRC}" 2>/dev/null; then
        echo "" >> "${BASHRC}"
        echo "# CNC Control CLI" >> "${BASHRC}"
        echo "${PATH_LINE}" >> "${BASHRC}"
    fi
    echo "Dodano PATH do ${BASHRC}. Uruchom: source ${BASHRC}"
fi

echo "Gotowe. Komendy dostepne: usb_mode, net_mode, status"
