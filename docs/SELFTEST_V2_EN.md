# Selftest v2 (Python, SHADOW-only)

## 1. Role in the system

`selftest v2` is the central diagnostic component:

- it is executed as a preflight gate in `integration_tests/test_runner.py`,
- it validates runtime compliance with the SHADOW A/B model,
- it acts as a CI gate (`critical > 0` blocks further phases).

Diagnostic entrypoints:

- `cnc-selftest` -> `cnc_control.selftest.cli`
- `tools/cnc_selftest.sh` -> wrapper that calls the Python module.

## 2. Validation scope

### Critical (blocking)

- missing slot A/B files (`CNC_USB_IMG_A`, `CNC_USB_IMG_B`),
- image mount/FAT validation failures (`ERR_FAT_INVALID`),
- missing `g_mass_storage` in `lsmod`,
- `CNC_ACTIVE_SLOT_FILE` inconsistency,
- missing `sudo -n` access for root-required operations (`ERR_MISSING_SUDO`).

### Warnings

- system noise entries (for example `bluetoothd`, `wpa_supplicant`),
- other system errors not directly related to CNC.

## 3. Root-required operations

All CAP_SYS_ADMIN-related operations are executed through a single function:

- `cnc_control.selftest.utils.run_root_command`.

Rules:

- it always runs `["sudo", "-n", *cmd]`,
- it returns `(returncode, stdout, stderr)` and never propagates exceptions,
- missing sudo access becomes a controlled critical error (`ERR_MISSING_SUDO`),
- selftest does not terminate with a traceback for this case.

## 4. SHADOW integration

Selftest v2 is aligned with the SHADOW A/B specification (`docs/SHADOW_MODE.md`):

- validates slot A/B presence and consistency,
- uses mount validation with `ro,loop,X-mount.mkdir`,
- uses SHADOW-compatible error codes (`ERR_FAT_INVALID`,
  `ERR_REBUILD_TIMEOUT`, `ERR_LOCK_CONFLICT`, `ERR_MISSING_SUDO`).

## 5. Determinism

The diagnostic contract is deterministic:

- no hostname-based text heuristics,
- one journal parser implementation (`cnc_control.selftest.journal`),
- one definition of criticality (`critical`),
- `status=FAILED` only when `critical > 0`,
- `warnings/system_noise` are informational and do not change exit code.

