# Instalacja systemowa

## Wymagania systemowe

- Raspberry Pi z Linuxem opartym o systemd (np. Raspberry Pi OS Lite)
- Python 3 (wymagany przez WebUI)
- Git
- Dostęp root (sudo)
- Pakiety SHADOW: `dosfstools`, `mtools`, `util-linux`, `inotify-tools`, `kmod`, `rsync`

### Platforma sprzętowa (docelowa i testowa)

- Urządzenie docelowe: **Raspberry Pi Zero W**.
- Aktualne testy: **Raspberry Pi Zero 2 W** (wyższa wydajność i wygodna współpraca z VS Code).
- Każda zmiana konfiguracji musi być przygotowana z myślą o docelowym **Raspberry Pi Zero W**.

## Szybki bootstrap na Raspberry Pi (zalecane)

Najprostsza instalacja bez ręcznego klonowania repozytorium:

```bash
cd ~
wget https://raw.githubusercontent.com/KrzysztofOle/cnc-control/main/tools/bootstrap_cnc.sh
chmod +x bootstrap_cnc.sh
./bootstrap_cnc.sh
```

Opcjonalnie możesz jawnie wskazać użytkownika instalacji:

```bash
CNC_INSTALL_USER=$USER ./bootstrap_cnc.sh
```

Skrypt przygotowuje system, pobiera repozytorium, tworzy `.venv`,
instaluje zależności i konfiguruje usługi systemd.

Po pierwszej instalacji wykonaj restart, aby aktywować `dwc2/UDC`:

```bash
sudo reboot
```

## Instalacja krok po kroku

```bash
git clone https://github.com/<twoj-user>/cnc-control.git ~/cnc-control
cd ~/cnc-control
python3 tools/bootstrap_env.py --target rpi
sudo ./tools/setup_system.sh
```

## Minimalne wymagania dla selftest v2

`cnc-selftest` uruchamiany jako zwykly uzytkownik wymaga dostepu do `sudo -n`
dla komend diagnostycznych wykonywanych z uprawnieniami root.
Brak tych uprawnien powoduje kontrolowany blad krytyczny `ERR_MISSING_SUDO`.

Minimalny profil sudoers:

```text
cnc ALL=(root) NOPASSWD: /usr/bin/mount
cnc ALL=(root) NOPASSWD: /usr/bin/umount
cnc ALL=(root) NOPASSWD: /usr/sbin/modprobe
cnc ALL=(root) NOPASSWD: /usr/bin/lsmod
```

Zasady:

- bez wildcard `*`,
- bez dostepu do innych polecen.

Zaleznosci aplikacji sa zarzadzane przez `pyproject.toml`.
Uslugi `cnc-webui.service` oraz `cnc-led.service` preferuja interpreter
`<repo>/.venv/bin/python3` (fallback do systemowego `python3`
przez skrypty `setup_webui.sh` i `setup_led_service.sh`, gdy venv nie istnieje).

## Profile srodowiska (DEV/RPI)

Docelowo obowiazuje jeden punkt wejscia do tworzenia `.venv`:

```bash
python3 tools/bootstrap_env.py --target <dev|integration|rpi>
```

- `--target rpi`:
  - instalacja zaleznosci z `pyproject.toml` (`--editable ".[rpi]"`),
  - do uruchamiania na Raspberry Pi.
- `--target dev`:
  - instalacja zaleznosci developerskich z `requirements_dev.txt`.
- `--target integration`:
  - instalacja zaleznosci do testow zewnetrznych z `requirements_integration.txt`
    (m.in. `paramiko`, `pysmb`).

Skrypt zapisuje marker targetu w `.venv/.cnc_target`, aby ograniczyc pomylki
przy uruchamianiu narzedzi w niewlasciwym srodowisku.

## Konfiguracja

Centralna konfiguracja znajduje się w pliku:

```
/etc/cnc-control/cnc-control.env
```

Skrypt `tools/setup_system.sh` kopiuje tam domyślny plik `config/cnc-control.env.example` tylko jeśli nie istnieje. Po instalacji uzupełnij wartości i zapisz plik.

## Zmienne środowiskowe (SHADOW-only)

Minimalny zestaw wymagany:

- `CNC_SHADOW_ENABLED=true`
- `CNC_MASTER_DIR=/var/lib/cnc-control/master`
- `CNC_USB_IMG_A=/var/lib/cnc-control/cnc_usb_a.img`
- `CNC_USB_IMG_B=/var/lib/cnc-control/cnc_usb_b.img`
- `CNC_ACTIVE_SLOT_FILE=/var/lib/cnc-control/shadow_active_slot.state`
- `CNC_SHADOW_STATE_FILE=/var/lib/cnc-control/shadow_state.json`
- `CNC_SHADOW_HISTORY_FILE=/var/lib/cnc-control/shadow_history.json`
- `CNC_SHADOW_SLOT_SIZE_MB=1024`
- `CNC_SHADOW_TMP_SUFFIX=.tmp`
- `CNC_SHADOW_LOCK_FILE=/var/run/cnc-shadow.lock`
- `CNC_SHADOW_CONFIG_VERSION=1`

## Awaryjny tryb Wi-Fi (Access Point)

Po starcie systemu usługa `cnc-wifi-fallback.service` przez określony czas
oczekuje na połączenie Wi-Fi zestawione przez NetworkManager. Jeśli połączenie
nie powstanie, uruchamiany jest tryb Access Point (`cnc-ap.service`).

Parametry AP:
- SSID: `CNC-SETUP`
- Hasło: `cnc-setup-1234` (WPA2-PSK)
- Adres IP: `192.168.50.1/24`
- DHCP: `192.168.50.10-192.168.50.50`
- Interfejs: `wlan0`

Domyślny timeout oczekiwania na Wi-Fi to `45` sekund. Możesz go zmienić przez
zmienną `WIFI_CONNECT_TIMEOUT` w `/etc/cnc-control/cnc-control.env`.

Połączenie z AP umożliwia konfigurację sieci przez Wi-Fi oraz dostęp do WebUI/SSH.

W trybie AP WebUI pokazuje listę sieci zapamiętaną tuż przed przełączeniem do AP
oraz umożliwia ręczne wpisanie SSID i hasła. Po zatwierdzeniu połączenia AP jest
automatycznie wyłączany, a system łączy się z wybraną siecią Wi‑Fi.

Uwaga:
- W trybie AP skanowanie sieci przez WebUI może być niedostępne, bo `wlan0` jest
  przełączony w tryb punktu dostępowego. Dlatego lista sieci pochodzi z cache
  zapisanego *przed* uruchomieniem AP.
- Cache skanu zapisywany jest domyślnie w `/tmp/cnc-wifi-scan.txt`
  (konfigurowalne przez `WIFI_SCAN_CACHE`).

Powrót do normalnego trybu klienta Wi-Fi:
- uzupełnij konfigurację Wi-Fi (NetworkManager),
- wykonaj restart systemu (po restarcie AP nie uruchomi się, jeśli Wi-Fi zadziała).

## Test cyklu AP (bez restartu)

Skrypt `tools/test_ap_cycle.sh` przełącza `wlan0` w tryb AP na określony czas,
a następnie automatycznie przywraca NetworkManager i łączy z Wi‑Fi.

Przykładowe uruchomienie z dłuższym czasem AP (sekundy):

```bash
sudo AP_TEST_TIME=300 tools/test_ap_cycle.sh
```

Parametry środowiskowe:
- `AP_TEST_TIME` – czas utrzymania AP w sekundach (domyślnie `180`).
- `WIFI_CONNECT_TIMEOUT` – timeout na powrót Wi‑Fi (domyślnie `60`).
- `POLL_INTERVAL` – interwał sprawdzania stanu (domyślnie `3`).
- `WIFI_SCAN_CACHE` – ścieżka cache skanu Wi‑Fi (domyślnie `/tmp/cnc-wifi-scan.txt`).

Skrypt testowy zapisuje cache skanu tuż przed przełączeniem w tryb AP, aby
odwzorować zachowanie trybu awaryjnego.

## PolicyKit (restart GUI)

Skrypt `tools/setup_system.sh` instaluje regułę PolicyKit, która pozwala
użytkownikowi WebUI (uzytkownik instalacji) wykonać `systemctl restart cnc-webui.service`
bez podawania hasła. Przy instalacji ręcznej skopiuj plik
`systemd/polkit/50-cnc-webui-restart.rules` do `/etc/polkit-1/rules.d/`.

## Samba (tylko smbd, port 445)

Konfiguracja Samby w tym projekcie jest celowo uproszczona:

- Uruchamiany jest wyłącznie `smbd.service`.
- `nmbd.service` (NetBIOS) jest wyłączony.
- `samba-ad-dc.service` nie jest używany (Raspberry Pi nie jest kontrolerem domeny).
- Serwer działa w trybie **standalone file server** i nasluchuje tylko na porcie 445.
- Udzial `cnc_usb` wskazuje:
  - `CNC_MASTER_DIR` gdy `CNC_SHADOW_ENABLED=true` (spojnie z WebUI),
  - `CNC_UPLOAD_DIR` (lub fallback `CNC_MOUNT_POINT`) poza trybem SHADOW.

### Dlaczego tylko smbd?

Wyłączenie NetBIOS i usług AD-DC skraca start systemu oraz zmniejsza liczbe procesow i ruchu
rozgloszeniowego w sieci. Ma to znaczenie w systemach CNC/embedded, gdzie priorytetem jest szybka
gotowosc do pracy, a nie pelna usluga przegladania sieci.

### Konsekwencje wydajnosciowe i funkcjonalne

- Szybszy boot i mniej obciazenia CPU/RAM (brak `nmbd` i `samba-ad-dc`).
- Brak oglaszania zasobow przez NetBIOS: udzial moze nie pojawiac sie automatycznie w "Otoczeniu sieci".
  Polacz sie bezposrednio:
  - Windows: `\\<IP_RPI>\cnc_usb`
  - macOS/Linux: `smb://<IP_RPI>/cnc_usb`

## Tryby pracy

- **SHADOW (obowiązujący)** – jedyny wspierany tryb produkcyjny i domyślna ścieżka rozwoju projektu.

## LED Status Indicator

Wskaźnik LED działa jako osobna usługa `cnc-led.service` i wykorzystuje:

- 3 diody WS2812/NeoPixel na `GPIO18`,
- demon `led_status.py`,
- CLI `led_status_cli.py`,
- IPC przez plik `/tmp/cnc_led_mode`.

Instalacja usługi:

```bash
chmod +x tools/setup_led_service.sh
sudo tools/setup_led_service.sh ~/cnc-control
```

Mapowanie trybów:

| Tryb | Kolor | Zachowanie |
|---|---|---|
| `BOOT` | żółty `(255, 180, 0)` | stały |
| `SHADOW_READY` | zielony `(0, 255, 0)` | stały |
| `SHADOW_SYNC` | niebieski `(0, 0, 255)` | stały |
| `AP` | niebieski `(0, 0, 255)` | mruganie `1 Hz` |
| `ERROR` | czerwony `(255, 0, 0)` | szybkie mruganie `3 Hz` |
| `IDLE` | biały przygaszony `(76, 76, 76)` | stały |

Bezpieczeństwo:
- jasność ograniczona do `0.3`,
- diody gasną przy zatrzymaniu usługi (np. `SIGTERM`),
- na systemach bez GPIO demon przechodzi w tryb fallback (brak crasha).

## Optymalizacja czasu uruchamiania

Poniższe decyzje skracają boot i ograniczają niepotrzebne zależności:

- **cloud-init** jest wyłączony i zamaskowany (wszystkie unity), bo w projekcie CNC
  nie jest wykorzystywany, a potrafi opóźniać start nawet o kilkadziesiąt sekund.
- **`nmbd.service` i `samba-ad-dc.service`** są wyłączone, bo nie są potrzebne do
  transferu plików; pozostaje tylko `smbd` (mniej procesów i broadcastów).
- **`NetworkManager-wait-online.service`** jest wyłączony i zamaskowany, aby boot
  nie czekał na pełną gotowość sieci (dla CNC ważniejsza jest szybka gotowość maszyny).
- **`cnc-usb.service`** startuje *po* `multi-user.target`, aby nie blokować osiągnięcia
  podstawowego stanu systemu podczas bootu.

## Szybki restart systemu – zasady i przyczyny opóźnień

- Restart z WebUI w trybie USB bywa wolny, bo system musi bezpiecznie odłączyć gadget USB,
  odczekać na zwolnienie magistrali przez kontroler i dopisać bufory systemu plików.
- `network-online.target` wydłuża start, gdy DHCP lub sieć nie są gotowe; w systemach CNC/embedded
  jest to niepożądane, bo priorytetem jest szybka gotowość maszyny, a nie pełna inicjalizacja sieci.
  W tym projekcie używamy tylko `network.target`, aby nie blokować bootu.
- Wyłącz `NetworkManager-wait-online.service`, ponieważ potrafi trzymać długie timeouty przy starcie
  i restarcie (zwłaszcza bez aktywnego DHCP lub linku):
  `sudo systemctl disable NetworkManager-wait-online.service`.
- Moduły `dwc2`, `g_mass_storage`, `g_ether` nie mogą być aktywowane statycznie w
  `/boot/config.txt` ani `/boot/cmdline.txt` — gadget ma być ładowany wyłącznie dynamicznie
  przez usługę `cnc-usb.service` / logikę runtime (SHADOW lub legacy).
- ZeroTier nie powinien blokować startu; jeśli jego unit ma `After=network-online.target`,
  ustaw override na `network.target` (np. `sudo systemctl edit zerotier-one`):

```ini
[Unit]
After=network.target
Wants=network.target
```

Zalecany restart: zatrzymaj aktywny eksport USB przez `sudo systemctl stop cnc-usb.service`,
odczekaj na odmontowanie obrazu, a następnie wykonaj `sudo systemctl reboot`
(lub `sudo reboot`) z SSH/terminala.

## Ukryte pliki systemowe

WebUI ukrywa w widoku listy plików pozycje zaczynające się od `.` oraz
typowe katalogi systemowe macOS (np. `.Spotlight-V100`, `.fseventsd`, `.Trashes`).
Takie wpisy są bezpiecznie ignorowane wyłącznie w warstwie prezentacji
i nie są usuwane z nośnika.

## Diagnostyka

```bash
systemctl cat cnc-webui
systemctl status cnc-webui
tr '\0' '\n' < /proc/<PID>/environ | grep CNC
```

Wstaw w miejscu `<PID>` identyfikator procesu z `systemctl status cnc-webui`.
