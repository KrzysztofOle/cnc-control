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
- 🧪 testy kompatybilności sprzętowej (zasilanie, peryferia)

> ⚠️ Projekt **nie ingeruje** w logikę PLC sterownika RichAuto – pełni rolę systemu wspomagającego.

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
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## ▶️ Uruchamianie

```bash
python main.py
```

---

## ⌨️ Komendy skrótowe (CLI)

Aby uruchamiać tryby jednym poleceniem (`usb_mode`, `net_mode`, `status`), zainstaluj skróty:

```bash
chmod +x tools/setup_commands.sh
./tools/setup_commands.sh
```

Skrypt tworzy linki do `usb_mode.sh`, `net_mode.sh`, `status.sh` i w razie potrzeby dodaje `~/.local/bin` do `PATH` (w `~/.bashrc`).

---

## 🧩 Usługi systemd (autostart)

Aby uruchamiać webui i tryb USB automatycznie po starcie systemu, użyj skryptów:

```bash
chmod +x tools/setup_webui.sh
sudo tools/setup_webui.sh ~/cnc-control

chmod +x tools/setup_usb_service.sh
sudo tools/setup_usb_service.sh ~/cnc-control
```

Skrypty tworzą jednostki `cnc-webui.service` i `cnc-usb.service`, włączają autostart i restartują usługi.

---

## 🌍 Zmienne środowiskowe

Poniższe zmienne można ustawić np. w unitach systemd przez `Environment=` albo `EnvironmentFile=`. Jeśli nie są ustawione, aplikacja/skrypty używają wartości domyślnych i działają dalej bez przerwania.

| Zmienna | Opis | Domyślna wartość | Użycie |
|---|---|---|---|
| `CNC_USB_MOUNT` | Punkt montowania USB (upload G-code) | `/mnt/cnc_usb` | `webui/app.py`, `net_mode.sh`, `usb_mode.sh`, `status.sh` |
| `CNC_NET_MODE_SCRIPT` | Ścieżka do skryptu trybu sieciowego | `<repo>/net_mode.sh` | `webui/app.py` |
| `CNC_USB_MODE_SCRIPT` | Ścieżka do skryptu trybu USB | `<repo>/usb_mode.sh` | `webui/app.py` |
| `CNC_CONTROL_REPO` | Ścieżka do repo (dla `git pull`) | `/home/andrzej/cnc-control` | `webui/app.py` |
| `CNC_WEBUI_LOG` | Ścieżka do pliku logu webui | `/var/log/cnc-control/webui.log` | `webui/app.py` |
| `CNC_WEBUI_SYSTEMD_UNIT` | Nazwa unita systemd dla webui | `cnc-webui.service` | `webui/app.py` |
| `CNC_WEBUI_LOG_SINCE` | Zakres czasu dla `journalctl` (np. `24 hours ago`) | `24 hours ago` | `webui/app.py` |
| `CNC_USB_IMG` | Obraz USB Mass Storage | `<repo>/usb/cnc_usb.img` | `net_mode.sh`, `usb_mode.sh`, `status.sh` |

---

## 📁 Struktura repozytorium

```
cnc-control/
├── AGENTS.md
├── README.md
├── README_EN.md
├── net_mode.sh
├── status.sh
├── usb_mode.sh
├── tools/
│   ├── setup_commands.sh
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
| `net_mode.sh` | Przełączanie trybu sieciowego (host/gadget). |
| `status.sh` | Szybki podgląd stanu systemu/połączeń. |
| `usb_mode.sh` | Przełączanie trybu USB dla Raspberry Pi. |
| `tools/` | Skrypty pomocnicze do konfiguracji środowiska. |
| `tools/setup_commands.sh` | Instalacja komend skrótowych `usb_mode`, `net_mode`, `status`. |
| `tools/setup_usb_service.sh` | Konfiguracja usługi `cnc-usb.service` dla `usb_mode.sh`. |
| `tools/setup_webui.sh` | Konfiguracja usługi `cnc-webui.service` dla webui. |
| `tools/setup_nmtui.sh` | Instalacja i uruchomienie `nmtui`. |
| `tools/setup_zerotier.sh` | Konfiguracja klienta ZeroTier. |
| `webui/` | Prosty interfejs WWW do obsługi narzędzi. |
| `webui/app.py` | Aplikacja webowa (serwer) dla webui. |

---

## ⚠️ Ograniczenia i uwagi

- ❌ brak bezpośredniej integracji z ctrlX PLC Engineering
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
