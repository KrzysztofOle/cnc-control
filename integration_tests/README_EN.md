# Integration Tests (Raspberry Pi)

## Purpose

`integration_tests/test_runner.py` runs integration checks from a developer machine
against a remote Raspberry Pi target.

The runner covers:
- SSH (remote diagnostics and commands),
- WebUI (file upload/delete),
- SMB (share write/delete),
- USB (gadget mode validation),
- NET->USB sync checks and timing measurements.

## Always-testing-latest-code flow

Every run starts with `phase_0_preflight`. By default it executes a remote CI refresh:

1. `git pull --ff-only` in the Raspberry Pi repository.
2. Python environment refresh:
   - create venv when missing: `python3 tools/bootstrap_env.py --target rpi --venv-dir ...`
   - then run: `pip install --editable '.[rpi]'`
3. Service configuration refresh:
   - `tools/setup_webui.sh`
   - `tools/setup_usb_service.sh`
   - `tools/setup_led_service.sh`
4. Diagnostics:
   - `./tools/cnc_selftest.sh --json`
   - `systemctl is-active cnc-webui.service`
   - `systemctl is-active cnc-usb.service`
   - `systemctl is-active cnc-led.service`
   - `journalctl -p 3 -n 20 --no-pager` (must have no CNC-related entries)

The runner includes automatic selftest repair for SHADOW
`Runtime LUN image matches expected`:
- detects this specific failed check,
- reloads `g_mass_storage` for the active slot (`A/B`),
- re-runs `cnc_selftest` once.

If any step fails, preflight is marked as `failed` and functional phases are skipped.

## Modes (`--mode`)

- `preflight`: only `phase_0_preflight`
- `ssh`: diagnostics alias (also preflight only)
- `net`: preflight + `phase_1_net_webui`
- `smb`: preflight + `phase_2_smb`
- `usb`: preflight + `phase_3_usb`
- `sync`: preflight + `phase_4_sync_net_to_usb`
- `perf`: preflight + `phase_5_performance`
- `all`: preflight + all functional phases (`1..5`)

`phase_6_cleanup` always runs at the end.

## Requirements

Local (DEV):
- active `.venv` with `integration` or `dev` target marker (`.cnc_target`),
- integration dependencies installed (`paramiko`, `requests`, `pysmb`).

Remote (RPi):
- project repository path (`CNC_CONTROL_REPO` or `/home/<ssh_user>/cnc-control`),
- SSH access,
- `sudo -n` access for root-required commands (setup/journal/env fallback),
- project systemd services available.

## Quick start

```bash
python3 tools/bootstrap_env.py --target integration
source .venv/bin/activate

python3 integration_tests/test_runner.py \
  --mode all \
  --host 192.168.7.139 \
  --ssh-user cnc \
  --ssh-key ~/.ssh/id_ed25519 \
  --smb-share cnc_usb
```

## Useful options

- `--report integration_tests/report.json` - JSON report output path.
- `--skip-target-check` - skip local `.cnc_target` validation.
- `--skip-remote-refresh` - skip remote CI refresh in preflight.
- `--remote-refresh-timeout 300` - timeout for pull/install/setup commands.
- `--remote-selftest-timeout 180` - timeout for `cnc_selftest`.
- `--disable-selftest-auto-repair` - disable one-shot SHADOW LUN auto-repair.
- `--switch-timeout 90` - timeout waiting for NET/USB mode switch.

## Report

Default report path:

`integration_tests/report.json`

Report includes:
- `summary` (`passed`, `failed`, `skipped`),
- per-phase `results[]`,
- `measurements` (upload/sync/switch timings),
- `remote_refresh` details from preflight (HEAD before/after, selftest, systemd, journal).

## Common failures

- `git pull --ff-only` fails due to merge/local changes on RPi.
- missing `sudo -n` for setup or `journalctl`.
- `systemctl is-active` not equal to `active`.
- CNC-related entries returned by `journalctl -p 3 -n 20`.
- missing `--smb-share` for `--mode all` or `--mode smb`.

## Safety

This project is connected to a real CNC machine:
- do not run tests during active machining,
- keep E-STOP available,
- start with safe-mode diagnostics first.
