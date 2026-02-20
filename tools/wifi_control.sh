#!/usr/bin/env bash
set -euo pipefail

NMCLI_BIN="/usr/bin/nmcli"
AP_SERVICE="${AP_SERVICE:-cnc-ap.service}"
WIFI_DEVICE="${WIFI_DEVICE:-wlan0}"

usage() {
  echo "Uzycie: wifi_control.sh scan | wifi_control.sh connect <ssid> [password] | wifi_control.sh profiles | wifi_control.sh connect-profile <name> | wifi_control.sh delete-profile <name>" >&2
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
  profiles)
    if [[ $# -ne 0 ]]; then
      usage
      exit 2
    fi
    exec sudo -n "${NMCLI_BIN}" -t -f NAME,TYPE connection show
    ;;
  connect)
    if [[ $# -lt 1 || $# -gt 2 ]]; then
      usage
      exit 2
    fi
    ssid="$1"
    password="${2:-}"
    previous_profile="$(
      sudo -n "${NMCLI_BIN}" -g GENERAL.CONNECTION device show "${WIFI_DEVICE}" 2>/dev/null \
        | head -n 1 \
        | tr -d '\r' \
        || true
    )"
    if [[ "${previous_profile}" == "--" ]]; then
      previous_profile=""
    fi
    restore_previous_profile() {
      if [[ -z "${previous_profile}" ]]; then
        return 0
      fi
      sudo -n "${NMCLI_BIN}" --wait 20 connection up id "${previous_profile}" ifname "${WIFI_DEVICE}" >/dev/null 2>&1 || true
    }
    if [[ -z "${ssid}" ]]; then
      fail 3 "SSID nie moze byc pusty."
    fi
    if command -v systemctl >/dev/null 2>&1; then
      sudo -n systemctl stop "${AP_SERVICE}" >/dev/null 2>&1 || true
    fi
    sudo -n "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed yes >/dev/null 2>&1 || true
    sudo -n "${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true
    sudo -n "${NMCLI_BIN}" device disconnect "${WIFI_DEVICE}" >/dev/null 2>&1 || true

    # Daj kartcie chwile na przejscie z trybu AP na klienta.
    # Give the Wi-Fi card a moment to switch from AP mode to client mode.
    for _ in 1 2 3; do
      sudo -n "${NMCLI_BIN}" dev wifi rescan ifname "${WIFI_DEVICE}" >/dev/null 2>&1 || true
      sleep 1
      if sudo -n "${NMCLI_BIN}" -t -f SSID dev wifi list ifname "${WIFI_DEVICE}" | grep -Fxq "${ssid}"; then
        break
      fi
    done

    connect_rc=0
    for attempt in 1 2; do
      connect_args=(sudo -n "${NMCLI_BIN}" --wait 20 dev wifi connect "${ssid}" ifname "${WIFI_DEVICE}")
      if [[ -n "${password}" ]]; then
        connect_args+=(password "${password}")
      fi
      if "${connect_args[@]}"; then
        exit 0
      fi
      connect_rc=$?
      if [[ "${connect_rc}" -eq 10 && "${attempt}" -lt 2 ]]; then
        sleep 2
        continue
      fi
      restore_previous_profile
      exit "${connect_rc}"
    done
    restore_previous_profile
    exit "${connect_rc}"
    ;;
  connect-profile)
    if [[ $# -ne 1 ]]; then
      usage
      exit 2
    fi
    profile_name="$1"
    previous_profile="$(
      sudo -n "${NMCLI_BIN}" -g GENERAL.CONNECTION device show "${WIFI_DEVICE}" 2>/dev/null \
        | head -n 1 \
        | tr -d '\r' \
        || true
    )"
    if [[ "${previous_profile}" == "--" ]]; then
      previous_profile=""
    fi
    restore_previous_profile() {
      if [[ -z "${previous_profile}" ]]; then
        return 0
      fi
      if [[ "${previous_profile}" == "${profile_name}" ]]; then
        return 0
      fi
      sudo -n "${NMCLI_BIN}" --wait 20 connection up id "${previous_profile}" ifname "${WIFI_DEVICE}" >/dev/null 2>&1 || true
    }
    if [[ -z "${profile_name}" ]]; then
      fail 3 "Nazwa profilu nie moze byc pusta."
    fi
    if command -v systemctl >/dev/null 2>&1; then
      sudo -n systemctl stop "${AP_SERVICE}" >/dev/null 2>&1 || true
    fi
    sudo -n "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed yes >/dev/null 2>&1 || true
    sudo -n "${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true
    sudo -n "${NMCLI_BIN}" device disconnect "${WIFI_DEVICE}" >/dev/null 2>&1 || true

    connect_rc=0
    for attempt in 1 2; do
      if sudo -n "${NMCLI_BIN}" --wait 20 connection up id "${profile_name}" ifname "${WIFI_DEVICE}"; then
        exit 0
      fi
      connect_rc=$?
      if [[ "${connect_rc}" -eq 10 && "${attempt}" -lt 2 ]]; then
        sleep 2
        continue
      fi
      restore_previous_profile
      exit "${connect_rc}"
    done
    restore_previous_profile
    exit "${connect_rc}"
    ;;
  delete-profile)
    if [[ $# -ne 1 ]]; then
      usage
      exit 2
    fi
    profile_name="$1"
    if [[ -z "${profile_name}" ]]; then
      fail 3 "Nazwa profilu nie moze byc pusta."
    fi
    exec sudo -n "${NMCLI_BIN}" connection delete id "${profile_name}"
    ;;
  *)
    usage
    exit 2
    ;;
esac
