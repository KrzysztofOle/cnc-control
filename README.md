# 🛠️ CNC Control – Integracja Raspberry Pi z RichAuto A11E

## 📌 Opis projektu

Repozytorium zawiera kod oraz konfigurację pomocniczą do **integracji sterownika CNC RichAuto A11E (DSP)** z **Raspberry Pi**. Celem projektu jest usprawnienie obsługi frezarki CNC poprzez:

- automatyzację wybranych czynności,
- wsparcie transferu plików G-code,
- rozszerzenie funkcjonalności sterownika bez ingerencji w jego firmware,
- wykorzystanie taniego i energooszczędnego komputera SBC.

Projekt jest rozwijany hobbystycznie, z naciskiem na **praktyczne zastosowanie w warsztacie CNC**.

---

## 🧩 Zakres funkcjonalny

- 📂 zarządzanie plikami G-code
- 🔌 komunikacja z urządzeniami USB / siecią lokalną
- ⚙️ skrypty pomocnicze dla Raspberry Pi
- 📶 awaryjny tryb Wi-Fi (AP `CNC-SETUP`) do konfiguracji sieci
- 🧪 testy kompatybilności sprzętowej (zasilanie, peryferia)

> ⚠️ Projekt **nie ingeruje** w logikę PLC sterownika RichAuto – pełni rolę systemu wspomagającego.

## 📣 Tryb pracy (wyłącznie SHADOW)

- Projekt działa wyłącznie w trybie `SHADOW`.
- Przeplyw opiera sie na katalogu `CNC_MASTER_DIR` oraz slotach obrazow USB (`CNC_USB_IMG_A` / `CNC_USB_IMG_B`).
- Szczegolowa specyfikacja: `docs/SHADOW_MODE.md`.

---

## 🖥️ Wymagania sprzętowe

| Element | Wymaganie |
|------|----------|
| Sterownik CNC | RichAuto A11 / A11E |
| SBC | Raspberry Pi Zero / Zero 2 W / 3B+ |
| Zasilanie | 5 V (min. 2 A zalecane) |
| Nośnik | microSD ≥ 8 GB |
| Sieć | Wi-Fi lub Ethernet (przez adapter USB) |

---

## 🎯 Platforma docelowa i testowa

- Urządzenie docelowe projektu: **Raspberry Pi Zero W**.
- Aktualna platforma testowa: **Raspberry Pi Zero 2 W** (lepsza wydajność i wygodniejsza współpraca z VS Code).
- Wszystkie zmiany konfiguracji muszą zachowywać kompatybilność z **Raspberry Pi Zero W** jako platformą docelową.

---

## 🧰 Wymagania programowe

- 🐧 Linux (Raspberry Pi OS Lite zalecany)
- 🐍 Python 3.9+
- 📦 pip / venv
- 🔧 Git

Opcjonalnie:
- Samba / FTP
- SSH

---

## 🚀 Instalacja

```bash
git clone https://github.com/<twoj-user>/cnc-control.git
cd cnc-control
python3 tools/bootstrap_env.py --target rpi
```

Dla komputera developerskiego:

```bash
python3 tools/bootstrap_env.py --target dev
```

Dla testow integracyjnych (SSH/SMB):

```bash
python3 tools/bootstrap_env.py --target integration
```

Szczegoly uruchamiania i faz testow: `integration_tests/README.md`.

---

## 🧱 Instalacja systemowa

Instrukcja przygotowania systemu po samym `git clone` znajduje się w `docs/INSTALL.md`.

### Szybki bootstrap na Raspberry Pi (zalecane)

Najprostsza metoda: zaloguj się na Raspberry Pi (lokalnie lub przez SSH) i wykonaj:

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

Skrypt automatycznie:
- zaktualizuje system (`apt update/upgrade`),
- utworzy `.venv` i zainstaluje zależności z `pyproject.toml` (z próbą dodatku `rpi-ws281x`),
- pobierze/odświeży repo `cnc-control` po HTTPS,
- uruchomi `setup_system.sh`, `setup_nmtui.sh`, `setup_webui.sh`, `setup_usb_service.sh`, `setup_led_service.sh`.

Opcjonalne nadpisanie użytkownika i katalogu repo:

```bash
CNC_INSTALL_USER=<USER_RPI> \
CNC_REPO_DIR=/home/<USER_RPI>/cnc-control \
CNC_VENV_DIR=/home/<USER_RPI>/cnc-control/.venv \
~/bootstrap_cnc.sh
```

---

## ▶️ Uruchamianie

```bash
python main.py
```

---

## 🧾 Wersjonowanie

Zasada: **tag Git = wersja aplikacji**. Używaj **annotated tags**.
Wersja pakietu Python jest wyznaczana automatycznie z tagów Git przez `setuptools-scm` (konfiguracja w `pyproject.toml`).
Plik `VERSION` nie jest używany.

Przykład:

```bash
git tag -a v0.1.14 -m "zerotier"
git push origin v0.1.10
```

Opis taga jest wyświetlany w WebUI.

---

## ⌨️ Narzędzia CLI (diagnostyka)

```bash
./status.sh
./tools/cnc_selftest.sh
./tools/cnc_selftest.sh --verbose
./tools/cnc_selftest.sh --json
```

---

## 🧩 Usługi systemd (autostart)

Aby uruchamiać webui i usługę eksportu USB automatycznie po starcie systemu (w tym przepływ SHADOW), użyj skryptów:

```bash
chmod +x tools/setup_webui.sh
sudo tools/setup_webui.sh ~/cnc-control

chmod +x tools/setup_usb_service.sh
sudo tools/setup_usb_service.sh ~/cnc-control

chmod +x tools/setup_led_service.sh
sudo tools/setup_led_service.sh ~/cnc-control
```

Skrypty tworzą jednostki `cnc-webui.service`, `cnc-usb.service` i `cnc-led.service`, włączają autostart i restartują usługi.

---

## LED Status Indicator

- Sprzęt: 3x WS2812/NeoPixel na `GPIO18`
- Jasność: `BRIGHTNESS=0.3` (ograniczenie poboru prądu)
- Logika: wszystkie 3 diody mają ten sam kolor i zachowują pełną synchronizację
- IPC: plik `/tmp/cnc_led_mode` (zapisywany przez `led_status_cli.py`, monitorowany przez `led_status.py`)
- Usługa: `cnc-led.service`

Mapowanie trybów:

| Tryb | Kolor | Zachowanie |
|---|---|---|
| `BOOT` | żółty `(255, 180, 0)` | stały |
| `USB` | czerwony `(255, 0, 0)` | stały |
| `UPLOAD` | zielony `(0, 255, 0)` | stały |
| `AP` | niebieski `(0, 0, 255)` | mruganie `1 Hz` |
| `ERROR` | czerwony `(255, 0, 0)` | szybkie mruganie `3 Hz` |
| `IDLE` | biały przygaszony `(76, 76, 76)` | stały |

---

## 🌐 Konfiguracja Wi-Fi (WebUI)

WebUI posiada prostą konfigurację Wi-Fi opartą o NetworkManager (`nmcli`).

Funkcje:
- szybkie przełączanie na zapisany profil bez ponownego wpisywania hasła,
- automatyczne blokowanie pola hasła dla sieci z zapisanym profilem,
- usuwanie zapisanego profilu z poziomu WebUI,
- przełącznik `Blokada AP` (działa do najbliższego restartu systemu),
- globalna blokada AP przez `CNC_AP_ENABLED` (system lock),
- automatyczny powrót do poprzedniego profilu po nieudanej próbie połączenia.

Wymagania:
- zainstalowany i uruchomiony NetworkManager (usługa `NetworkManager`)
- reguły sudo dla `nmcli` (bez hasła) dla użytkownika uruchamiającego WebUI
- WebUI uruchamiaj jako zwykły użytkownik (nie jako root)
- hasła Wi-Fi nie są zapisywane przez aplikację ani skrypty

Minimalny sudoers (plik `/etc/sudoers.d/cnc-wifi`):

```bash
andrzej ALL=(root) NOPASSWD: /usr/bin/nmcli *
andrzej ALL=(root) NOPASSWD: /usr/bin/systemctl stop cnc-ap.service
```

Skrypt pomocniczy używany przez WebUI: `tools/wifi_control.sh`.

### Blokada trybu AP

Zmienna `CNC_AP_ENABLED` domyslnie ma wartosc `false`.

Przy `CNC_AP_ENABLED=false`:
- UI pokazuje badge `AP: DISABLED (SYSTEM LOCK)`,
- kontrolki AP pozostaja widoczne, ale sa nieaktywne (wyszarzone),
- backend odrzuca zmiane stanu AP przez API kodem `403` z komunikatem:
  `AP mode disabled by system configuration`.

Logika AP pozostaje w kodzie i moze zostac odblokowana przez ustawienie
`CNC_AP_ENABLED=true`.

---

## ⚡ Szybki restart systemu – zasady i przyczyny opóźnień

- `network-online.target` wydłuża start, gdy DHCP lub sieć nie są gotowe; w systemach CNC/embedded
  jest to niepożądane, bo priorytetem jest szybka gotowość maszyny, a nie pełna inicjalizacja sieci.
  W tym projekcie używamy tylko `network.target`, aby nie blokować bootu.
- Wyłącz `NetworkManager-wait-online.service`, ponieważ potrafi trzymać długie timeouty przy starcie
  i restarcie (zwłaszcza bez aktywnego DHCP lub linku):
  `sudo systemctl disable NetworkManager-wait-online.service`.

---

## ⚙️ Konfiguracja systemowa i zmienne środowiskowe

Konfiguracja jest centralnie zarzadzana przez plik:

```
/etc/cnc-control/cnc-control.env
```

Plik ten jest wczytywany przez systemd (`EnvironmentFile=`), logike SHADOW/WebUI oraz narzedzia diagnostyczne. Brak pliku lub brak wymaganych zmiennych powoduje jawny blad.

Szybki start:

```bash
sudo mkdir -p /etc/cnc-control
sudo cp config/cnc-control.env.example /etc/cnc-control/cnc-control.env
sudo nano /etc/cnc-control/cnc-control.env
```

Wymagane zmienne dla trybu SHADOW-only:

| Zmienna | Opis | Domyslna wartosc | Uzycie |
|---|---|---|---|
| `CNC_SHADOW_ENABLED` | Flaga trybu SHADOW (ustaw `true`) | `false` | `webui/app.py`, `tools/cnc_selftest.sh` |
| `CNC_MASTER_DIR` | Katalog roboczy SHADOW (zrodlo plikow) | `/var/lib/cnc-control/master` | `shadow/watcher_service.py`, `shadow/rebuild_engine.py` |
| `CNC_USB_IMG_A` | Sciezka obrazu USB dla slotu A | `/var/lib/cnc-control/cnc_usb_a.img` | `shadow/slot_manager.py`, `tools/cnc_selftest.sh` |
| `CNC_USB_IMG_B` | Sciezka obrazu USB dla slotu B | `/var/lib/cnc-control/cnc_usb_b.img` | `shadow/slot_manager.py`, `tools/cnc_selftest.sh` |
| `CNC_UPLOAD_DIR` | Katalog uploadu z WebUI | brak (wymagane) | `webui/app.py`, `tools/cnc_selftest.sh` |

Pozostale zmienne (opcjonalne):

| Zmienna | Opis | Domyslna wartosc | Uzycie |
|---|---|---|---|
| `CNC_CONTROL_REPO` | Sciezka do repo (dla `git pull`) | `/home/andrzej/cnc-control` | `webui/app.py` |
| `CNC_WEBUI_LOG` | Sciezka do pliku logu webui | `/var/log/cnc-control/webui.log` | `webui/app.py` |
| `CNC_WEBUI_SYSTEMD_UNIT` | Nazwa unita systemd dla webui | `cnc-webui.service` | `webui/app.py` |
| `CNC_WEBUI_LOG_SINCE` | Zakres czasu dla `journalctl` (np. `24 hours ago`) | `24 hours ago` | `webui/app.py` |
| `CNC_AP_BLOCK_FLAG` | Sciezka pliku tymczasowej blokady AP | `/dev/shm/cnc-ap-blocked.flag` | `webui/app.py`, `tools/wifi_fallback.sh` |
| `CNC_AP_ENABLED` | Globalny przelacznik AP (`true`/`false`) | `false` | `webui/app.py` |
| `CNC_USB_LABEL` | Etykieta woluminu FAT widoczna na hoście USB (max 11 znakow) | `CNC_USB` | `tools/setup_system.sh`, `shadow/rebuild_engine.py` |
| `CNC_ACTIVE_SLOT_FILE` | Plik aktywnego slotu (`A`/`B`) | `/var/lib/cnc-control/shadow_active_slot.state` | `shadow/slot_manager.py`, `tools/cnc_selftest.sh` |
| `CNC_SHADOW_STATE_FILE` | Plik stanu SHADOW (JSON) | `/var/lib/cnc-control/shadow_state.json` | `shadow/state_store.py`, `webui/app.py` |
| `CNC_SHADOW_HISTORY_FILE` | Plik historii przebudow SHADOW | `/var/lib/cnc-control/shadow_history.json` | `shadow/shadow_manager.py`, `webui/app.py` |
| `CNC_SHADOW_LOCK_FILE` | Sciezka locka przebudowy SHADOW | `/var/run/cnc-shadow.lock` | `shadow/lock_manager.py`, `tools/cnc_selftest.sh` |
| `CNC_SHADOW_DEBOUNCE_SECONDS` | Opoznienie laczenia zdarzen watchera | `4` | `shadow/shadow_manager.py` |
| `CNC_SHADOW_SLOT_SIZE_MB` | Rozmiar slotu obrazu USB | `256` | `shadow/rebuild_engine.py` |
| `CNC_SHADOW_TMP_SUFFIX` | Sufiks pliku tymczasowego przebudowy | `.tmp` | `shadow/rebuild_engine.py`, `shadow/slot_manager.py` |
| `CNC_SHADOW_HISTORY_LIMIT` | Limit wpisow historii przebudow | `50` | `shadow/shadow_manager.py` |

---

## 📁 Struktura repozytorium

```
cnc-control/
├── AGENTS.md
├── README.md
├── README_EN.md
├── pyproject.toml
├── config/
├── led_status.py
├── led_status_cli.py
├── status.sh
├── tools/
│   ├── setup_led_service.sh
│   ├── setup_usb_service.sh
│   ├── setup_webui.sh
│   ├── setup_nmtui.sh
│   └── setup_zerotier.sh
└── webui/
    └── app.py
```

### 📄 Pliki i katalogi

| Plik/Katalog | Opis |
|---|---|
| `AGENTS.md` | Zasady współpracy i dokumentacji w projekcie. |
| `README.md` | Dokumentacja bazowa w języku polskim. |
| `README_EN.md` | Dokumentacja pomocnicza w języku angielskim. |
| `pyproject.toml` | Konfiguracja pakietu Python i zależności (`pip install .`, `.[rpi]`). |
| `config/` | Przykladowe pliki konfiguracyjne. |
| `config/cnc-control.env.example` | Przykklad centralnej konfiguracji (EnvironmentFile). |
| `led_status.py` | Demon LED WS2812 (GPIO18) monitorujacy IPC i sterujacy stanem LED. |
| `led_status_cli.py` | CLI do zapisu trybu LED przez IPC (`/tmp/cnc_led_mode`). |
| `status.sh` | Szybki podgląd stanu systemu/połączeń. |
| `tools/` | Skrypty pomocnicze do konfiguracji środowiska. |
| `tools/setup_led_service.sh` | Konfiguracja usługi `cnc-led.service` dla `led_status.py`. |
| `tools/setup_usb_service.sh` | Konfiguracja usługi `cnc-usb.service` dla eksportu SHADOW. |
| `tools/setup_webui.sh` | Konfiguracja usługi `cnc-webui.service` dla webui. |
| `tools/setup_nmtui.sh` | Instalacja i uruchomienie `nmtui`. |
| `tools/setup_zerotier.sh` | Konfiguracja klienta ZeroTier. |
| `tools/wifi_control.sh` | Skrypt pomocniczy do skanowania i łączenia Wi-Fi (`nmcli`). |
| `webui/` | Prosty interfejs WWW do obsługi narzędzi. |
| `webui/app.py` | Aplikacja webowa (serwer) dla webui. |

---

## ⚠️ Ograniczenia i uwagi

- ❌ brak modyfikacji firmware RichAuto
- ⚠️ port USB w A11E ma ograniczoną wydajność prądową

---

## 🧭 Kierunki rozwoju

- 📊 monitoring pracy maszyny
- 🌐 interfejs WWW
- 🔄 automatyczna synchronizacja G-code
- 🧾 logowanie zdarzeń

---

## 📄 Licencja

MIT

---

## 👤 Autor

Krzysztof  
Python • OpenCV • CNC • Automatyzacja
