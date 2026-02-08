#!/usr/bin/env bash
set -euo pipefail

NMCLI_BIN="${NMCLI_BIN:-/usr/bin/nmcli}"
WIFI_DEVICE="${WIFI_DEVICE:-wlan0}"
WIFI_CONNECT_TIMEOUT="${WIFI_CONNECT_TIMEOUT:-45}"
POLL_INTERVAL="${POLL_INTERVAL:-3}"
AP_SERVICE="${AP_SERVICE:-cnc-ap.service}"
WIFI_SCAN_CACHE="${WIFI_SCAN_CACHE:-/tmp/cnc-wifi-scan.txt}"

log() {
  local msg="$1"
  echo "[wifi-fallback] ${msg}"
  if command -v logger >/dev/null 2>&1; then
    logger -t cnc-wifi-fallback "${msg}"
  fi
}

start_ap() {
  if [ ! -f "/etc/systemd/system/${AP_SERVICE}" ]; then
    log "Brak pliku unita ${AP_SERVICE}."
    return 1
  fi

  if [ -x "${NMCLI_BIN}" ]; then
    echo "[wifi-fallback] Odłączanie wlan0 od NetworkManager"
    nmcli device disconnect wlan0 || true
    nmcli device set wlan0 managed no || true
    sleep 1
  else
    log "Brak nmcli. Pomijam odlaczanie ${WIFI_DEVICE} od NetworkManager."
  fi

  if ! ip -4 addr show dev wlan0 | grep -q "inet "; then
    ip addr flush dev wlan0 || true
    ip addr add 192.168.50.1/24 dev wlan0
    ip link set wlan0 up
  fi

  log "Zatrzymywanie domyslnych uslug hostapd/dnsmasq"
  systemctl stop hostapd.service >/dev/null 2>&1 || true
  systemctl stop dnsmasq.service >/dev/null 2>&1 || true

  log "Uruchamiam ${AP_SERVICE}"
  if systemctl start "${AP_SERVICE}"; then
    log "Tryb AP uruchomiony."
    return 0
  fi

  log "Blad uruchamiania ${AP_SERVICE}."
  return 1
}

save_wifi_scan_cache() {
  if [ ! -x "${NMCLI_BIN}" ]; then
    log "Brak nmcli. Pomijam zapis cache skanowania Wi-Fi."
    return 0
  fi

  log "Zapisuje liste sieci Wi-Fi do cache: ${WIFI_SCAN_CACHE}"
  if "${NMCLI_BIN}" -t -f IN-USE,SSID,SECURITY,SIGNAL dev wifi list > "${WIFI_SCAN_CACHE}.tmp" 2>/dev/null; then
    mv "${WIFI_SCAN_CACHE}.tmp" "${WIFI_SCAN_CACHE}"
    chmod 644 "${WIFI_SCAN_CACHE}" || true
    return 0
  fi

  rm -f "${WIFI_SCAN_CACHE}.tmp" || true
  log "Nie udalo sie zapisac cache skanowania Wi-Fi."
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
save_wifi_scan_cache || true
start_ap
