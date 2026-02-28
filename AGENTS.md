# 🤖 Zasady pracy asystenta (AGENTS)

Ten dokument definiuje zasady współpracy przy projekcie  
**CNC Control – Raspberry Pi & RichAuto A11/A11E**.

Plik **AGENTS.md jest prowadzony wyłącznie w języku polskim** i stanowi źródło prawdy dla całego repozytorium.

---

## 🎯 Zakres projektu

Projekt dotyczy systemu wspomagającego obsługę frezarki CNC ze sterownikiem **RichAuto A11 / A11E**, z wykorzystaniem **Raspberry Pi** jako komputera pomocniczego.

Zakres projektu:

- obsługa i transfer plików G-code,
- automatyzacja czynności pomocniczych,
- integracja sieciowa i USB,
- narzędzia wspierające pracę operatora.

❗ Projekt **nie modyfikuje firmware ani logiki PLC** sterownika RichAuto.

---

## 🧭 Zasady ogólne

1. Komunikacja, opisy zmian i polecenia są w języku **polskim**.
2. Dokumentacja w projekcie jest:
   - **bazowo w języku polskim (PL)**,
   - **dodatkowo w języku angielskim (EN)**.
3. Językiem nadrzędnym zawsze jest **PL**.
4. W przypadku rozbieżności treści, wersja **PL ma pierwszeństwo**.
5. Cała dokumentacja musi być formatowana w **Markdown**.
6. Opisy commitów zawsze podawaj najpierw po **angielsku**, a następnie dodaj **krótkie streszczenie po polsku**.

---

## 📄 Dokumentacja (*.md)

1. Każdy plik dokumentacji posiada:
   - wersję bazową w języku polskim: `NAZWA.md`,
   - wersję angielską: `NAZWA_EN.md`.
2. Przykłady:
   - `README.md` + `README_EN.md`
   - `INSTALL.md` + `INSTALL_EN.md`
3. Plik **AGENTS.md występuje wyłącznie w wersji PL** (brak AGENTS_EN.md).
4. Wersja EN powinna być spójna logicznie z PL, ale nie musi być tłumaczeniem dosłownym.

---

## 💻 Kod źródłowy

1. Język programowania: **Python**.
2. Nazwy zmiennych, funkcji, klas i modułów są w języku **angielskim**.
3. Komentarze w kodzie są **dwujęzyczne**:
   - najpierw **PL**,
   - następnie **EN**.
4. Przykład:

   ```python
   # PL: Inicjalizacja połączenia USB
   # EN: Initialize USB connection
   ```

5. Nie usuwaj istniejących komentarzy bez uzasadnienia.
6. Przestrzegaj standardu **PEP 8**.

---

## 🧪 Testowanie

1. Preferowany framework testowy: **pytest**.
2. Zmiany wprowadzaj stopniowo, umożliwiając testy cząstkowe.
3. Nie proponuj nowych funkcjonalności przed przetestowaniem bieżących zmian.

---

## 📄 README

1. `README.md` aktualizuj tylko przy **istotnych zmianach funkcjonalnych**.
2. Przy każdej aktualizacji `README.md` **zaktualizuj również `README_EN.md`**.
3. Drobne zmiany kosmetyczne nie wymagają aktualizacji README.

---

## 🔁 Metodyka pracy developerskiej i wdrożeniowej

Projekt stosuje rozdzielony model pracy:

### 1️⃣ Środowisko developerskie (lokalne)

- Kod jest modyfikowany i analizowany na maszynie developerskiej (PC / Mac).
- Maszyna developerska **nie jest docelowym Raspberry Pi**.
- Zmiany są weryfikowane lokalnie (analiza kodu, testy jednostkowe, przegląd logiki).

### 2️⃣ Commit i push

Po pozytywnej weryfikacji:

- CODEX wykonuje:
  - `git add`
  - `git commit`
  - `git push`
- Opis commitu musi być zgodny z zasadami określonymi w AGENTS.md.

### 3️⃣ Aktualizacja środowiska testowego (Raspberry Pi)

Po wypchnięciu zmian na serwer:

CODEX łączy się przez SSH z jednym z testowych Raspberry Pi:

- `ssh cnc@192.168.7.139`
- `ssh andrzej@192.168.7.110`

Następnie:

- przechodzi do katalogu repozytorium `cnc-control`,
- wykonuje `git pull`,
- aktualizuje środowisko (jeśli wymagane),
- uruchamia odpowiednie skrypty (`usb_mode.sh`, `net_mode.sh`, `status.sh`),
- przeprowadza testy diagnostyczne,
- weryfikuje konfigurację systemową oraz usługi systemd.

### 4️⃣ Zasada bezpieczeństwa

- Testy wykonuj najpierw w trybie bezpiecznym.
- Nie przeprowadzaj testów przy aktywnym procesie obróbki.
- Zakładaj możliwość niepoprawnej konfiguracji Raspberry Pi.

Model ten zapewnia:

- oddzielenie warstwy rozwoju od warstwy sprzętowej,
- powtarzalność wdrożeń,
- minimalizację ryzyka uszkodzenia maszyny CNC.

---

## 🧪 Tryb CI – Automatyczny operator wdrożeniowy

W projekcie obowiązuje deterministyczna sekwencja działań wdrożeniowych.
CODEX działa jak uproszczony operator CI (Continuous Integration).

---

### 1️⃣ Faza DEV (lokalna)

Warunki wstępne:

- Kod zmodyfikowany lokalnie.
- Testy jednostkowe (pytest) przechodzą bez błędów.
- Brak błędów składni (`python -m py_compile` lub równoważne).

Dopiero po spełnieniu powyższych warunków możliwy jest commit.

---

### 2️⃣ Commit i push (repozytorium)

Sekwencja obowiązkowa:

git add .
git commit -m "" -m ""
git push

Zabronione:
- commit bez testów,
- bezpośrednia edycja plików na Raspberry Pi bez wcześniejszego push.

---

### 3️⃣ Faza TEST (Raspberry Pi)

Po wypchnięciu zmian:

CODEX łączy się z jednym z testowych Raspberry Pi:

- `ssh cnc@192.168.7.139`
- `ssh andrzej@192.168.7.110`

Następnie wykonuje sekwencję:

cd ~/cnc-control
git pull --ff-only
source .venv/bin/activate
pip install -editable ".[rpi]"
cnc_selftest -json

Dodatkowo sprawdza:

systemctl is-active cnc-webui
systemctl is-active cnc-usb
systemctl is-active cnc-led

---

### 4️⃣ Warunki sukcesu wdrożenia

Wdrożenie uznaje się za poprawne, gdy:

- `git pull` kończy się bez konfliktów,
- `cnc_selftest` zwraca exit code 0,
- wszystkie wymagane usługi systemd mają stan `active`,
- brak ERROR w `journalctl -p 3 -n 20`.

---

### 5️⃣ Warunki niepowodzenia

Za błąd wdrożenia uznaje się:

- konflikt merge,
- niezerowy exit code selftest,
- usługa systemd w stanie `failed`,
- wyjątek Python podczas startu WebUI.

W przypadku błędu:

- nie wykonuj dalszych testów funkcjonalnych,
- zgłoś błąd i opisz logi,
- nie kontynuuj wdrożenia na innych urządzeniach.

---

### 6️⃣ Zasada integralności środowiska

Raspberry Pi nie jest środowiskiem developerskim.

Zabronione:

- ręczne poprawki kodu bez commit,
- zmiany bez odzwierciedlenia w repo,
- instalacje zależności poza `.venv`.

---

Model CI zapewnia:

- powtarzalność wdrożeń,
- kontrolę jakości,
- minimalizację ryzyka dla maszyny CNC.

---

## ⚠️ Bezpieczeństwo

Projekt dotyczy pracy z rzeczywistą maszyną CNC.

Zawsze:

- zapewnij dostęp do **E-STOP**,
- testuj zmiany bez narzędzia skrawającego,
- zakładaj możliwość awarii systemu wspomagającego.

---

## 🧭 Zasada nadrzędna

W przypadku konfliktu zasad:

- **AGENTS.md ma najwyższy priorytet**,
- wszelkie wątpliwości zgłaszaj przed wprowadzeniem zmian.
