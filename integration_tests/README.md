# Testy integracyjne (Raspberry Pi)

## Cel

`integration_tests/test_runner.py` uruchamia testy integracyjne z maszyny developerskiej
przeciwko zdalnemu Raspberry Pi.

Runner pokrywa:
- SSH (diagnostyka i komendy zdalne),
- WebUI (upload/usuwanie plików),
- SMB (zapis/usuwanie przez udział),
- USB (walidacja trybu gadget + opcjonalny odczyt host-side),
- NET->USB sync oraz pomiary czasowe.
- SHADOW watcher (wykrywanie zmian i rebuild),
- synchronizację plików SHADOW (master -> aktywny slot),
- gotowość G-code w aktywnym runtime LUN SHADOW.

## Zasada uruchamiania na najnowszym kodzie

Każde uruchomienie rozpoczyna się od `phase_0_preflight`, która domyślnie wykonuje
zdalny etap odświeżenia CI:

1. `git pull --ff-only` w repo na Raspberry Pi.
2. Aktualizacja środowiska Python:
   - jeśli brak venv: `python3 tools/bootstrap_env.py --target rpi --venv-dir ...`
   - następnie: `pip install --editable '.[rpi]'`
3. Odświeżenie konfiguracji usług:
   - `tools/setup_webui.sh`
   - `tools/setup_usb_service.sh`
   - `tools/setup_led_service.sh`
4. Diagnostyka:
   - selftest v2 uruchamiany przez Python (`cnc_control.selftest.core.run_selftest`)
   - `systemctl is-active cnc-webui.service`
   - `systemctl is-active cnc-usb.service`
   - `systemctl is-active cnc-led.service`

Preflight nie posiada lokalnej implementacji filtra journal i nie duplikuje
definicji `critical`. Jedynym źródłem prawdy diagnostyki jest selftest v2.

Jeśli którykolwiek krok powyżej zakończy się błędem, preflight kończy się statusem
`failed`, a kolejne fazy są pomijane.

## Tryby (`--mode`)

- `preflight`: tylko `phase_0_preflight`
- `ssh`: alias diagnostyczny (także tylko preflight)
- `net`: preflight + `phase_1_net_webui`
- `smb`: preflight + `phase_2_smb`
- `usb`: preflight + `phase_3_usb` (z `--usb-host-mount` także bezpośredni odczyt pliku z hosta USB)
- `sync`: preflight + `phase_4_sync_net_to_usb`
- `perf`: preflight + `phase_5_performance`
- `shadow`: preflight + fazy SHADOW (`phase_shadow_1_watcher`, `phase_shadow_2_sync_files`, `phase_shadow_3_gcode_runtime`)
- `all`: preflight + wszystkie fazy funkcjonalne (`1..5` + fazy SHADOW)

`phase_6_cleanup` uruchamia się zawsze na końcu.

## Wymagania

Lokalnie (DEV):
- aktywne `.venv` z targetem `integration` lub `dev` (marker `.cnc_target`),
- zainstalowane zależności integracyjne (`paramiko`, `requests`, `pysmb`).

Zdalnie (RPi):
- repozytorium projektu (`CNC_CONTROL_REPO` lub `/home/<ssh_user>/cnc-control`),
- dostęp SSH,
- dostęp `sudo -n` do komend wymagających uprawnień root (setup/journal/env fallback),
- działające usługi systemd projektu.

## Szybki start

```bash
python3 tools/bootstrap_env.py --target integration
source .venv/bin/activate

python3 integration_tests/test_runner.py \
  --mode all \
  --host 192.168.7.139 \
  --ssh-user cnc \
  --ssh-key ~/.ssh/id_ed25519 \
  --smb-share cnc_usb
```

## Przydatne opcje

- `--report integration_tests/report.json` - ścieżka raportu JSON.
- `--skip-target-check` - pomija walidację markera `.cnc_target`.
- `--skip-remote-refresh` - pomija etap zdalnego odświeżenia CI w preflight.
- `--remote-refresh-timeout 300` - timeout dla pull/install/setup.
- `--remote-selftest-timeout 180` - timeout dla selftest v2.
- `--disable-selftest-auto-repair` - wyłącza jednorazową auto-naprawę SHADOW LUN.
- `--switch-timeout 90` - timeout oczekiwania na przełączenie NET/USB.
- `--usb-host-mount /Volumes/CNC_USB` - lokalna ścieżka montowania pamięci gadget na maszynie DEV; włącza bezpośredni test odczytu host-side w fazie USB.
- `--usb-host-read-timeout 25` - timeout oczekiwania na widoczność pliku testowego po stronie hosta USB.

## Raport

Domyślny raport zapisuje się do:

`integration_tests/report.json`

Raport zawiera:
- `summary` (`passed`, `failed`, `skipped`),
- `results[]` dla każdej fazy,
- `measurements` (czasy upload/sync/switch),
- szczegóły `remote_refresh` z preflight (HEAD before/after, selftest, systemd, journal).

## Najczęstsze problemy

- Błąd `git pull --ff-only`: lokalne zmiany/konflikt na RPi.
- Brak `sudo -n`: setup usług lub `journalctl` nie może się wykonać.
- `systemctl is-active` != `active`: runner przerywa testy.
- `critical > 0` w selftest v2: runner traktuje to jako błąd wdrożenia.
- Brak `--smb-share` dla `--mode all` lub `--mode smb`: błąd walidacji argumentów.

## Bezpieczeństwo

Projekt dotyczy realnej maszyny CNC:
- testy uruchamiaj poza aktywną obróbką,
- zapewnij dostęp do E-STOP,
- najpierw wykonuj testy w trybie bezpiecznym.
