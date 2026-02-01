# Instalacja systemowa

## Wymagania systemowe

- Raspberry Pi z Linuxem opartym o systemd (np. Raspberry Pi OS Lite)
- Python 3 (wymagany przez WebUI)
- Git
- Dostęp root (sudo)
- Repozytorium w ścieżce: `/home/andrzej/cnc-control` (wymagane przez unit systemd)

## Instalacja krok po kroku

```bash
git clone https://github.com/<twoj-user>/cnc-control.git /home/andrzej/cnc-control
cd /home/andrzej/cnc-control
sudo ./tools/setup_system.sh
```

## Konfiguracja

Centralna konfiguracja znajduje się w pliku:

```
/etc/cnc-control/cnc-control.env
```

Skrypt `tools/setup_system.sh` kopiuje tam domyślny plik `config/cnc-control.env.example` tylko jeśli nie istnieje. Po instalacji uzupełnij wartości i zapisz plik.

## Zmienne środowiskowe

- `CNC_USB_IMG` – ścieżka do obrazu USB Mass Storage.
- `CNC_MOUNT_POINT` – punkt montowania obrazu (upload G-code).
- `CNC_UPLOAD_DIR` – katalog, do którego WebUI zapisuje pliki.

## Tryby pracy

- **USB (CNC)** – Raspberry Pi udostępnia obraz jako pamięć masowa USB dla kontrolera.
- **NET (UPLOAD)** – upload plików G-code przez sieć, bez trybu USB.

Tryb jest przełączany przez skrypty `usb_mode.sh` i `net_mode.sh`.

## Diagnostyka

```bash
systemctl cat cnc-webui
systemctl status cnc-webui
tr '\0' '\n' < /proc/<PID>/environ | grep CNC
```

Wstaw w miejscu `<PID>` identyfikator procesu z `systemctl status cnc-webui`.
