#!/usr/bin/env bash
set -euo pipefail

NMCLI_BIN="${NMCLI_BIN:-/usr/bin/nmcli}"
WIFI_DEVICE="${WIFI_DEVICE:-wlan0}"
AP_SERVICE="${AP_SERVICE:-cnc-ap.service}"
AP_TEST_TIME="${AP_TEST_TIME:-180}"
WIFI_CONNECT_TIMEOUT="${WIFI_CONNECT_TIMEOUT:-60}"
POLL_INTERVAL="${POLL_INTERVAL:-3}"

log() {
  local msg="$1"
  echo "[ap-cycle] ${msg}"
  if command -v logger >/dev/null 2>&1; then
    logger -t cnc-ap-cycle "${msg}"
  fi
}

fail() {
  local code="$1"
  shift
  log "$*"
  exit "${code}"
}

require_root() {
  if [ "${EUID}" -ne 0 ]; then
    fail 1 "Skrypt musi byc uruchomiony jako root (sudo)."
  fi
}

validate_inputs() {
  if [[ ! "${AP_TEST_TIME}" =~ ^[0-9]+$ ]] || [ "${AP_TEST_TIME}" -lt 1 ]; then
    fail 2 "AP_TEST_TIME musi byc dodatnia liczba (sekundy)."
  fi
  if [[ ! "${WIFI_CONNECT_TIMEOUT}" =~ ^[0-9]+$ ]] || [ "${WIFI_CONNECT_TIMEOUT}" -lt 1 ]; then
    fail 2 "WIFI_CONNECT_TIMEOUT musi byc dodatnia liczba (sekundy)."
  fi
  if [[ ! "${POLL_INTERVAL}" =~ ^[0-9]+$ ]] || [ "${POLL_INTERVAL}" -lt 1 ]; then
    fail 2 "POLL_INTERVAL musi byc dodatnia liczba (sekundy)."
  fi
  if [ ! -x "${NMCLI_BIN}" ]; then
    fail 127 "Brak nmcli pod ${NMCLI_BIN}."
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    fail 127 "Brak systemctl (systemd)."
  fi
  if ! systemctl cat "${AP_SERVICE}" >/dev/null 2>&1; then
    fail 4 "Brak unita systemd lub problem z systemd: ${AP_SERVICE}."
  fi
}

AP_ACTIVE=0
RESTORED=0

cleanup() {
  if [ "${RESTORED}" -eq 1 ]; then
    return
  fi

  log "Awaryjne sprzatanie po przerwaniu."
  set +e
  if [ "${AP_ACTIVE}" -eq 1 ]; then
    systemctl stop "${AP_SERVICE}" >/dev/null 2>&1 || true
  fi
  if [ -x "${NMCLI_BIN}" ]; then
    "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed yes >/dev/null 2>&1 || true
    "${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true
    "${NMCLI_BIN}" device connect "${WIFI_DEVICE}" >/dev/null 2>&1 || true
  fi
  set -e
}

trap cleanup EXIT

start_ap() {
  log "Odłączanie ${WIFI_DEVICE} od NetworkManager"
  "${NMCLI_BIN}" device disconnect "${WIFI_DEVICE}" >/dev/null 2>&1 || true
  "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed no >/dev/null 2>&1 || true
  sleep 1

  log "Zatrzymywanie domyslnych uslug hostapd/dnsmasq"
  systemctl stop hostapd.service >/dev/null 2>&1 || true
  systemctl stop dnsmasq.service >/dev/null 2>&1 || true

  log "Uruchamiam ${AP_SERVICE}"
  systemctl start "${AP_SERVICE}"
  if ! systemctl is-active --quiet "${AP_SERVICE}"; then
    fail 5 "Nie udalo sie uruchomic ${AP_SERVICE}."
  fi
  AP_ACTIVE=1
  log "Tryb AP aktywny."
}

stop_ap() {
  log "Zatrzymywanie ${AP_SERVICE}"
  systemctl stop "${AP_SERVICE}" || true
  AP_ACTIVE=0
}

restore_networkmanager() {
  log "Przywracanie ${WIFI_DEVICE} pod NetworkManager"
  "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed yes
  "${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true
  "${NMCLI_BIN}" device connect "${WIFI_DEVICE}" >/dev/null 2>&1 || true

  local deadline_ts
  deadline_ts=$(( $(date +%s) + WIFI_CONNECT_TIMEOUT ))

  while [ "$(date +%s)" -lt "${deadline_ts}" ]; do
    local device_state
    device_state="$("${NMCLI_BIN}" -t -f DEVICE,STATE d 2>/dev/null | grep "^${WIFI_DEVICE}:" || true)"
    log "Stan ${WIFI_DEVICE}: ${device_state:-brak}"
    if echo "${device_state}" | grep -q ":connected$"; then
      log "Polaczenie Wi-Fi przywrocone."
      return 0
    fi
    sleep "${POLL_INTERVAL}"
  done

  fail 6 "Nie udalo sie przywrocic polaczenia Wi-Fi w ${WIFI_CONNECT_TIMEOUT}s."
}

main() {
  require_root
  validate_inputs

  log "Start testu AP (czas=${AP_TEST_TIME}s, device=${WIFI_DEVICE}, unit=${AP_SERVICE})."

  start_ap
  log "Utrzymuje AP przez ${AP_TEST_TIME}s..."
  sleep "${AP_TEST_TIME}"

  stop_ap
  restore_networkmanager

  RESTORED=1
  log "Test zakonczony."
}

main "$@"
