# Selftest v2 (Python, SHADOW-only)

## 1. Rola w systemie

`selftest v2` jest centralnym komponentem diagnostycznym projektu:

- stanowi etap preflight w `integration_tests/test_runner.py`,
- waliduje zgodnosc runtime z modelem SHADOW A/B,
- pelni role bramki CI (`critical > 0` blokuje dalsze fazy).

Wejscie diagnostyczne:

- `cnc-selftest` -> `cnc_control.selftest.cli`
- `tools/cnc_selftest.sh` -> wrapper wywolujacy modul Python.

## 2. Zakres walidacji

### Krytyczne (blokujace)

- brak slotu A/B (`CNC_USB_IMG_A`, `CNC_USB_IMG_B`),
- bledy mount/FAT obrazu (kod `ERR_FAT_INVALID`),
- brak `g_mass_storage` w `lsmod`,
- niespojnosc `CNC_ACTIVE_SLOT_FILE`,
- brak dostepu `sudo -n` dla operacji root (`ERR_MISSING_SUDO`).

### Ostrzezenia

- wpisy noise z uslug systemowych (np. `bluetoothd`, `wpa_supplicant`),
- pozostale bledy systemowe niezawiazane bezposrednio z CNC.

## 3. Operacje wymagajace root

Wszystkie operacje wymagajace uprawnien CAP_SYS_ADMIN sa wykonywane przez
`sudo -n` w jednej funkcji:

- `cnc_control.selftest.utils.run_root_command`.

Zasady:

- funkcja zawsze uruchamia `["sudo", "-n", *cmd]`,
- zwraca `(returncode, stdout, stderr)` i nie propaguje wyjatkow,
- brak dostepu sudo daje kontrolowany blad krytyczny `ERR_MISSING_SUDO`,
- selftest nie konczy sie tracebackiem dla tego przypadku.

## 4. Integracja z SHADOW

Selftest v2 jest powiazany ze specyfikacja SHADOW A/B (`docs/SHADOW_MODE.md`):

- waliduje istnienie i spojność slotow A/B,
- wykonuje mount test w trybie `ro,loop,X-mount.mkdir`,
- stosuje kody bledow zgodne z katalogiem SHADOW (`ERR_FAT_INVALID`,
  `ERR_REBUILD_TIMEOUT`, `ERR_LOCK_CONFLICT`, `ERR_MISSING_SUDO`).

## 5. Determinizm

Kontrakt diagnostyczny jest deterministyczny:

- brak heurystyk tekstowych opartych o hostname,
- jedna implementacja parsera journal (`cnc_control.selftest.journal`),
- jedna definicja krytycznosci (`critical`),
- `status=FAILED` tylko gdy `critical > 0`,
- `warnings/system_noise` sa informacyjne i nie zmieniaja exit code.

