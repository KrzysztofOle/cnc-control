#!/usr/bin/env bash
set -euo pipefail

NMCLI_BIN="${NMCLI_BIN:-/usr/bin/nmcli}"
WIFI_DEVICE="${WIFI_DEVICE:-wlan0}"
WIFI_CONNECT_TIMEOUT="${WIFI_CONNECT_TIMEOUT:-45}"
POLL_INTERVAL="${POLL_INTERVAL:-3}"
AP_SERVICE="${AP_SERVICE:-cnc-ap.service}"

log() {
  local msg="$1"
  echo "[wifi-fallback] ${msg}"
  if command -v logger >/dev/null 2>&1; then
    logger -t cnc-wifi-fallback "${msg}"
  fi
}

start_ap() {
  if systemctl is-active --quiet "${AP_SERVICE}"; then
    log "Tryb AP jest juz aktywny (${AP_SERVICE})."
    return 0
  fi

  if ! systemctl list-unit-files --type=service | grep -q "^${AP_SERVICE}"; then
    log "Brak unita ${AP_SERVICE}."
    return 1
  fi

  if [ -x "${NMCLI_BIN}" ]; then
    log "Odlaczanie ${WIFI_DEVICE} od NetworkManager (bez zatrzymywania uslugi)"
    "${NMCLI_BIN}" device disconnect "${WIFI_DEVICE}" >/dev/null 2>&1 || true
    "${NMCLI_BIN}" device set "${WIFI_DEVICE}" managed no >/dev/null 2>&1 || true
  else
    log "Brak nmcli. Pomijam odlaczanie ${WIFI_DEVICE} od NetworkManager."
  fi

  log "Zatrzymywanie domyslnych uslug hostapd/dnsmasq"
  systemctl stop hostapd.service >/dev/null 2>&1 || true
  systemctl stop dnsmasq.service >/dev/null 2>&1 || true

  log "Uruchamianie ${AP_SERVICE}"
  if systemctl start "${AP_SERVICE}"; then
    systemctl status --no-pager "${AP_SERVICE}" || true
    log "Tryb AP uruchomiony."
    return 0
  fi

  log "Blad uruchamiania ${AP_SERVICE}."
  return 1
}

if [ "${EUID}" -ne 0 ]; then
  log "Skrypt musi byc uruchomiony jako root."
  exit 1
fi

if [ ! -x "${NMCLI_BIN}" ]; then
  log "Brak nmcli pod ${NMCLI_BIN}. Przelaczam na tryb AP."
  start_ap
  exit $?
fi

log "Start sprawdzania Wi-Fi (timeout=${WIFI_CONNECT_TIMEOUT}s, interwal=${POLL_INTERVAL}s, device=${WIFI_DEVICE})."
"${NMCLI_BIN}" radio wifi on >/dev/null 2>&1 || true

now_ts="$(date +%s)"
deadline_ts=$((now_ts + WIFI_CONNECT_TIMEOUT))

while [ "$(date +%s)" -lt "${deadline_ts}" ]; do
  wifi_state="$("${NMCLI_BIN}" -t -f WIFI g 2>/dev/null || true)"
  device_states="$("${NMCLI_BIN}" -t -f DEVICE,STATE d 2>/dev/null || true)"
  log "nmcli WIFI=${wifi_state}"
  log "nmcli DEVICE,STATE=${device_states}"

  if echo "${device_states}" | grep -q "^${WIFI_DEVICE}:connected$"; then
    log "Wi-Fi polaczone na ${WIFI_DEVICE}. Tryb AP nie jest potrzebny."
    exit 0
  fi

  sleep "${POLL_INTERVAL}"
done

log "Brak polaczenia Wi-Fi po ${WIFI_CONNECT_TIMEOUT}s."
start_ap
