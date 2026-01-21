#!/usr/bin/env bash
set -euo pipefail

# --- poprawka: skrypt przygotowania nmtui i polecenia wifi — 2026-01-21T18:42:28+01:00 ---

#
# Skrypt do uruchomienia nmtui z uprawnieniami roota przez sudo bez hasła.
#
# Użycie:
#   sudo ./tools/setup_nmtui.sh
#


if [[ "${EUID}" -ne 0 ]]; then
  echo "Uruchom skrypt z sudo, np.: sudo ./tools/setup_nmtui.sh" >&2
  exit 1
fi

if [[ -z "${SUDO_USER:-}" || "${SUDO_USER}" == "root" ]]; then
  echo "Brak docelowego uzytkownika (SUDO_USER). Uruchom przez sudo z konta docelowego." >&2
  exit 1
fi

TARGET_USER="${SUDO_USER}"

apt update
apt install -y network-manager wireless-tools iproute2

systemctl enable NetworkManager
systemctl start NetworkManager

NMTUI_PATH="$(command -v nmtui || true)"
if [[ -z "${NMTUI_PATH}" ]]; then
  echo "Nie znaleziono nmtui po instalacji." >&2
  exit 1
fi

cat > /usr/local/bin/wifi <<EOF
#!/usr/bin/env bash
exec sudo -n "${NMTUI_PATH}"
EOF

chmod 0755 /usr/local/bin/wifi

cat > "/etc/sudoers.d/wifi-nmtui" <<EOF
${TARGET_USER} ALL=(root) NOPASSWD: ${NMTUI_PATH}
EOF

chmod 0440 /etc/sudoers.d/wifi-nmtui

echo "Gotowe. Uzyj polecenia: wifi"
