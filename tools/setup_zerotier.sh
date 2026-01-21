#!/usr/bin/env bash
set -euo pipefail

# Skrypt do instalacji i konfiguracji ZeroTier na Debian/Raspberry Pi OS.
#
# Uzycie:
#   sudo ./tools/setup_zerotier.sh
#   sudo ./tools/setup_zerotier.sh <NETWORK_ID>
#
# Opcjonalnie podaj NETWORK_ID, aby od razu dolaczyc do sieci.
#

if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom skrypt z sudo, np.: sudo ./tools/setup_zerotier.sh" >&2
  exit 1
fi

if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
  echo "Brak docelowego uzytkownika (SUDO_USER). Uruchom przez sudo z konta docelowego." >&2
  exit 1
fi

NETWORK_ID="${1:-}"

if [[ -n "${NETWORK_ID}" && ! "${NETWORK_ID}" =~ ^[0-9a-fA-F]{16}$ ]]; then
  echo "Nieprawidlowy NETWORK_ID. Oczekiwane 16 znakow hex." >&2
  exit 1
fi

apt update
apt install -y curl

curl -s https://install.zerotier.com | bash

systemctl enable zerotier-one
systemctl start zerotier-one

if [[ -n "${NETWORK_ID}" ]]; then
  zerotier-cli join "${NETWORK_ID}"
fi

zerotier-cli info

echo "Gotowe."
if [[ -n "${NETWORK_ID}" ]]; then
  echo "Autoryzuj urzadzenie w panelu ZeroTier Central, aby uzyskac dostep do sieci."
else
  echo "Aby dolaczyc do sieci: sudo zerotier-cli join <NETWORK_ID>"
fi
