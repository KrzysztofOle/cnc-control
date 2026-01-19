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

## 📁 Struktura repozytorium

```
cnc-control/
├── main.py
├── requirements.txt
├── scripts/
├── config/
├── docs/
└── README.md
```

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
