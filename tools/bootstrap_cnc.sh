#!/usr/bin/env bash
set -euo pipefail

REPO_URL_DEFAULT="https://github.com/KrzysztofOle/cnc-control.git"
GIT_BRANCH_DEFAULT="main"
PREFERRED_USER_DEFAULT="andrzej"
APT_PACKAGES=(
    git
    python3
    python3-venv
    python3-pip
    build-essential
    python3-dev
    network-manager
    openssh-server
    curl
    samba
    dosfstools
    mtools
    util-linux
    inotify-tools
    kmod
    rsync
)

SELECTED_BRANCH="${CNC_GIT_BRANCH:-${GIT_BRANCH_DEFAULT}}"

parse_args() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --branch)
                if [ "$#" -lt 2 ] || [ -z "${2}" ]; then
                    echo "Brak wartosci dla opcji --branch."
                    exit 1
                fi
                SELECTED_BRANCH="$2"
                shift 2
                ;;
            --branch=*)
                SELECTED_BRANCH="${1#*=}"
                if [ -z "${SELECTED_BRANCH}" ]; then
                    echo "Brak wartosci dla opcji --branch."
                    exit 1
                fi
                shift
                ;;
            *)
                echo "Nieznana opcja: $1"
                echo "Uzycie: $0 [--branch <nazwa-galezi>]"
                exit 1
                ;;
        esac
    done
}

is_allowed_origin_url() {
    local url="$1"
    if [[ "${url}" =~ (^|[:/])KrzysztofOle/cnc-control(\.git)?$ ]]; then
        return 0
    fi
    return 1
}

resolve_remote_ref_type() {
    local remote="$1"
    local repo_dir="${2:-}"
    if [ -n "${repo_dir}" ]; then
        if run_as_install_user git -C "${repo_dir}" ls-remote --exit-code --heads "${remote}" "${SELECTED_BRANCH}" >/dev/null 2>&1; then
            printf '%s\n' "branch"
            return 0
        fi
        if run_as_install_user git -C "${repo_dir}" ls-remote --exit-code --tags "${remote}" "${SELECTED_BRANCH}" >/dev/null 2>&1; then
            printf '%s\n' "tag"
            return 0
        fi
        return 1
    fi

    if run_as_install_user git ls-remote --exit-code --heads "${remote}" "${SELECTED_BRANCH}" >/dev/null 2>&1; then
        printf '%s\n' "branch"
        return 0
    fi
    if run_as_install_user git ls-remote --exit-code --tags "${remote}" "${SELECTED_BRANCH}" >/dev/null 2>&1; then
        printf '%s\n' "tag"
        return 0
    fi
    return 1
}

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

validate_shadow_env() {
    local env_file="/etc/cnc-control/cnc-control.env"
    local missing=()
    local key=""
    local syntax_error=""

    if [ ! -f "${env_file}" ]; then
        echo "[ERROR] Brak pliku konfiguracji: ${env_file}"
        exit 1
    fi

    if ! syntax_error="$(bash -n "${env_file}" 2>&1)"; then
        echo "[ERROR] Niepoprawna skladnia pliku ${env_file}."
        echo "[ERROR] Szczegoly parsera bash:"
        printf '%s\n' "${syntax_error}" | sed 's/^/[ERROR]   /'
        exit 1
    fi

    # shellcheck source=/etc/cnc-control/cnc-control.env
    set -a
    source "${env_file}"
    set +a

    if [ "${CNC_SHADOW_ENABLED:-}" != "true" ]; then
        echo "[ERROR] Wymagany tryb SHADOW-only: CNC_SHADOW_ENABLED musi miec wartosc 'true'."
        exit 1
    fi

    for key in \
        CNC_MASTER_DIR \
        CNC_USB_IMG_A \
        CNC_USB_IMG_B \
        CNC_ACTIVE_SLOT_FILE \
        CNC_SHADOW_STATE_FILE \
        CNC_SHADOW_HISTORY_FILE \
        CNC_SHADOW_SLOT_SIZE_MB \
        CNC_SHADOW_TMP_SUFFIX \
        CNC_SHADOW_LOCK_FILE \
        CNC_SHADOW_CONFIG_VERSION
    do
        if [ -z "${!key:-}" ]; then
            missing+=("${key}")
        fi
    done

    if [ "${#missing[@]}" -gt 0 ]; then
        echo "[ERROR] Brak wymaganych zmiennych SHADOW w ${env_file}: ${missing[*]}"
        exit 1
    fi
}

echo "=== CNC Bootstrap Start ==="
parse_args "$@"

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
VENV_DIR="${CNC_VENV_DIR:-${REPO_DIR}/.venv}"
TARGET_REF_TYPE=""
COMMIT_HASH=""

echo "[1/9] Aktualizacja systemu"
run_as_root apt-get update
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

echo "[2/9] Instalacja pakietow"
run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"

echo "[3/9] Uruchamianie uslug bazowych"
run_as_root systemctl enable --now ssh
run_as_root systemctl enable --now NetworkManager

echo "[4/9] Klonowanie lub aktualizacja repozytorium (${REPO_URL})"
run_as_install_user mkdir -p "$(dirname "${REPO_DIR}")"
if [ -d "${REPO_DIR}/.git" ]; then
    if ! run_as_install_user git -C "${REPO_DIR}" diff --quiet || ! run_as_install_user git -C "${REPO_DIR}" diff --cached --quiet; then
        echo "ERROR: Local changes detected in repository. Aborting bootstrap."
        exit 1
    fi

    ORIGIN_URL="$(run_as_install_user git -C "${REPO_DIR}" remote get-url origin 2>/dev/null || true)"
    if [ -z "${ORIGIN_URL}" ]; then
        echo "ERROR: Cannot determine repository origin URL. Aborting bootstrap."
        exit 1
    fi
    if ! is_allowed_origin_url "${ORIGIN_URL}"; then
        echo "WARNING: Unexpected origin URL: ${ORIGIN_URL}"
        echo "ERROR: Repository origin must point to KrzysztofOle/cnc-control. Aborting bootstrap."
        exit 1
    fi

    if ! TARGET_REF_TYPE="$(resolve_remote_ref_type origin "${REPO_DIR}")"; then
        echo "ERROR: Requested ref '${SELECTED_BRANCH}' does not exist on origin."
        exit 1
    fi

    run_as_install_user git -C "${REPO_DIR}" config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"
    run_as_install_user git -C "${REPO_DIR}" fetch origin --tags

    if [ "${TARGET_REF_TYPE}" = "branch" ]; then
        if ! run_as_install_user git -C "${REPO_DIR}" checkout "${SELECTED_BRANCH}"; then
            echo "ERROR: Failed to switch to requested branch."
            exit 1
        fi
        CURRENT_BRANCH="$(run_as_install_user git -C "${REPO_DIR}" rev-parse --abbrev-ref HEAD)"
        if [ "${CURRENT_BRANCH}" != "${SELECTED_BRANCH}" ]; then
            echo "ERROR: Failed to switch to requested branch."
            exit 1
        fi
        run_as_install_user git -C "${REPO_DIR}" pull --ff-only
        echo "Using Git branch: ${SELECTED_BRANCH}"
    else
        if ! run_as_install_user git -C "${REPO_DIR}" checkout --detach "tags/${SELECTED_BRANCH}"; then
            echo "ERROR: Failed to checkout requested tag."
            exit 1
        fi
        echo "Using tag: ${SELECTED_BRANCH}"
    fi
elif [ -d "${REPO_DIR}" ] && [ -n "$(ls -A "${REPO_DIR}")" ]; then
    echo "Katalog ${REPO_DIR} istnieje i nie jest repozytorium git. Przerwano."
    exit 1
else
    if ! is_allowed_origin_url "${REPO_URL}"; then
        echo "WARNING: Unexpected origin URL: ${REPO_URL}"
        echo "ERROR: Repository origin must point to KrzysztofOle/cnc-control. Aborting bootstrap."
        exit 1
    fi

    if ! TARGET_REF_TYPE="$(resolve_remote_ref_type "${REPO_URL}")"; then
        echo "ERROR: Requested ref '${SELECTED_BRANCH}' does not exist on origin."
        exit 1
    fi

    if [ "${TARGET_REF_TYPE}" = "branch" ]; then
        if ! run_as_install_user git clone --branch "${SELECTED_BRANCH}" --single-branch "${REPO_URL}" "${REPO_DIR}"; then
            echo "[ERROR] Nie udalo sie sklonowac galezi '${SELECTED_BRANCH}' z ${REPO_URL}."
            exit 1
        fi
        echo "Using Git branch: ${SELECTED_BRANCH}"
    else
        if ! run_as_install_user git clone "${REPO_URL}" "${REPO_DIR}"; then
            echo "ERROR: Failed to clone repository for tag checkout."
            exit 1
        fi
        if ! run_as_install_user git -C "${REPO_DIR}" checkout --detach "tags/${SELECTED_BRANCH}"; then
            echo "ERROR: Failed to checkout requested tag."
            exit 1
        fi
        echo "Using tag: ${SELECTED_BRANCH}"
    fi

    ORIGIN_URL="$(run_as_install_user git -C "${REPO_DIR}" remote get-url origin 2>/dev/null || true)"
    if ! is_allowed_origin_url "${ORIGIN_URL}"; then
        echo "WARNING: Unexpected origin URL: ${ORIGIN_URL}"
        echo "ERROR: Repository origin must point to KrzysztofOle/cnc-control. Aborting bootstrap."
        exit 1
    fi
fi

COMMIT_HASH="$(run_as_install_user git -C "${REPO_DIR}" rev-parse --short HEAD)"
echo "Using commit: ${COMMIT_HASH}"

PYTHON3_BIN="$(command -v python3 || true)"
if [ -z "${PYTHON3_BIN}" ]; then
    echo "Brak python3 w PATH."
    exit 1
fi

echo "[5/9] Konfiguracja srodowiska Python (venv + pyproject)"
BOOTSTRAP_ENV_SCRIPT="${REPO_DIR}/tools/bootstrap_env.py"
if [ ! -f "${BOOTSTRAP_ENV_SCRIPT}" ]; then
    echo "[ERROR] Brak skryptu bootstrap_env.py: ${BOOTSTRAP_ENV_SCRIPT}"
    exit 1
fi

if ! run_as_install_user "${PYTHON3_BIN}" "${BOOTSTRAP_ENV_SCRIPT}" --target rpi --venv-dir "${VENV_DIR}"; then
    echo "[ERROR] Nie udalo sie skonfigurowac srodowiska przez bootstrap_env.py (--target rpi)."
    exit 1
fi

TARGET_MARKER="${VENV_DIR}/.cnc_target"
if [ ! -f "${TARGET_MARKER}" ]; then
    echo "[ERROR] Brak wymaganego markera targetu: ${TARGET_MARKER}"
    echo "[ERROR] Oczekiwano pliku po uruchomieniu: python3 tools/bootstrap_env.py --target rpi"
    exit 1
fi

echo "[6/9] Instalacja konfiguracji systemowej cnc-control"
run_as_root env SUDO_USER="${INSTALL_USER}" CNC_INSTALL_USER="${INSTALL_USER}" bash "${REPO_DIR}/tools/setup_system.sh"
validate_shadow_env

echo "[7/9] Instalacja skrotow CLI"
run_as_root bash "${REPO_DIR}/tools/setup_commands.sh"

echo "[8/9] Instalacja menu Wi-Fi (nmtui + komenda wifi)"
run_as_root env SUDO_USER="${INSTALL_USER}" bash "${REPO_DIR}/tools/setup_nmtui.sh"

echo "[9/9] Instalacja uslug systemd (WebUI + SHADOW USB Export + LED)"
run_as_root env SUDO_USER="${INSTALL_USER}" CNC_VENV_DIR="${VENV_DIR}" bash "${REPO_DIR}/tools/setup_webui.sh" "${REPO_DIR}"
if run_as_root bash "${REPO_DIR}/tools/setup_usb_service.sh" "${REPO_DIR}"; then
    echo "[INFO] Usluga USB zainstalowana."
else
    echo "[WARN] Nie udalo sie skonfigurowac uslugi USB. Kontynuuje konfiguracje."
fi

if run_as_root env CNC_VENV_DIR="${VENV_DIR}" bash "${REPO_DIR}/tools/setup_led_service.sh" "${REPO_DIR}"; then
    echo "[INFO] Usluga LED zainstalowana."
else
    echo "[WARN] Nie udalo sie skonfigurowac uslugi LED."
fi

echo "=== CNC Bootstrap Done ==="
echo "Repozytorium: ${REPO_DIR}"
echo "Srodowisko Python: ${VENV_DIR}"
echo "Uzytkownik uslug: ${INSTALL_USER}"
echo "Sprawdz: systemctl status cnc-webui cnc-usb cnc-led"
echo "Uwaga: po pierwszej instalacji wykonaj reboot, aby aktywowac dwc2/UDC."
