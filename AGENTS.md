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
