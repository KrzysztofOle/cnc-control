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

## PolicyKit (restart GUI)

Skrypt `tools/setup_system.sh` instaluje regułę PolicyKit, która pozwala
użytkownikowi WebUI (`andrzej`) wykonać `systemctl restart cnc-webui.service`
bez podawania hasła. Przy instalacji ręcznej skopiuj plik
`systemd/polkit/50-cnc-webui-restart.rules` do `/etc/polkit-1/rules.d/`.

## Samba (tylko smbd, port 445)

Konfiguracja Samby w tym projekcie jest celowo uproszczona:

- Uruchamiany jest wyłącznie `smbd.service`.
- `nmbd.service` (NetBIOS) jest wyłączony.
- `samba-ad-dc.service` nie jest używany (Raspberry Pi nie jest kontrolerem domeny).
- Serwer działa w trybie **standalone file server** i nasluchuje tylko na porcie 445.
- Udostepniany katalog to `/mnt/cnc_usb` (udzial `cnc_usb`).

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

- **USB (CNC)** – Raspberry Pi udostępnia obraz jako pamięć masowa USB dla kontrolera.
- **NET (UPLOAD)** – upload plików G-code przez sieć, bez trybu USB.

Tryb jest przełączany przez skrypty `usb_mode.sh` i `net_mode.sh`.

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
  przez `usb_mode.sh`.
- ZeroTier nie powinien blokować startu; jeśli jego unit ma `After=network-online.target`,
  ustaw override na `network.target` (np. `sudo systemctl edit zerotier-one`):

```ini
[Unit]
After=network.target
Wants=network.target
```

Zalecany restart: przełącz na tryb sieciowy (`net_mode.sh`), odczekaj na odmontowanie obrazu,
a następnie wykonaj `sudo systemctl reboot` (lub `sudo reboot`) z SSH/terminala.

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
