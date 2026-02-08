#!/usr/bin/env bash
set -euo pipefail

NMCLI_BIN="/usr/bin/nmcli"
AP_SERVICE="${AP_SERVICE:-cnc-ap.service}"
WIFI_DEVICE="${WIFI_DEVICE:-wlan0}"

usage() {
  echo "Uzycie: wifi_control.sh scan | wifi_control.sh connect <ssid> <password>" >&2
}

fail() {
  local code="$1"
  shift
  echo "$*" >&2
  exit "$code"
}

if [[ ! -x "${NMCLI_BIN}" ]]; then
  fail 127 "Brak nmcli pod ${NMCLI_BIN}."
fi

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

command="$1"
shift

case "${command}" in
  scan)
    if [[ $# -ne 0 ]]; then
      usage
      exit 2
    fi
    exec sudo -n "${NMCLI_BIN}" -t -f IN-USE,SSID,SECURITY,SIGNAL dev wifi list
    ;;
  connect)
    if [[ $# -ne 2 ]]; then
      usage
      exit 2
    fi
    ssid="$1"
    password="$2"
    if [[ -z "${ssid}" ]]; then
      fail 3 "SSID nie moze byc pusty."
    fi
    if [[ -z "${password}" ]]; then
      fail 3 "Haslo nie moze byc puste."
    fi
    if command -v systemctl >/dev/null 2>&1; then
      sudo -n systemctl stop "${AP_SERVICE}" >/dev/null 2>&1 || true
    fi
    sudo -n "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed yes >/dev/null 2>&1 || true
    sudo -n "${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true
    exec sudo -n "${NMCLI_BIN}" dev wifi connect "${ssid}" password "${password}"
    ;;
  *)
    usage
    exit 2
    ;;
esac
