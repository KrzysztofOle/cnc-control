# System Installation

## System requirements

- Raspberry Pi running a systemd-based Linux (e.g. Raspberry Pi OS Lite)
- Python 3 (required by WebUI)
- Git
- Root access (sudo)
- Repository located at `/home/andrzej/cnc-control` (required by the systemd unit)

### Hardware platform (target and test)

- Target device: **Raspberry Pi Zero W**.
- Current tests: **Raspberry Pi Zero 2 W** (higher performance and smooth VS Code workflow).
- Every configuration change must be designed for the target **Raspberry Pi Zero W**.

## Quick bootstrap on Raspberry Pi (recommended)

Simplest installation path without manual repository clone:

```bash
cd ~
wget https://raw.githubusercontent.com/KrzysztofOle/cnc-control/main/tools/bootstrap_cnc.sh
chmod +x bootstrap_cnc.sh
./bootstrap_cnc.sh
```

Optionally, you can set the installation user explicitly:

```bash
CNC_INSTALL_USER=$USER ./bootstrap_cnc.sh
```

The script prepares the system, clones/updates the repository, creates `.venv`,
installs dependencies, and configures systemd services.

## Step-by-step installation

```bash
git clone https://github.com/<your-user>/cnc-control.git /home/andrzej/cnc-control
cd /home/andrzej/cnc-control
python3 tools/bootstrap_env.py --target rpi
sudo ./tools/setup_system.sh
```

Application dependencies are managed via `pyproject.toml`.
`cnc-webui.service` and `cnc-led.service` prefer the interpreter at
`/home/andrzej/cnc-control/.venv/bin/python3` (with fallback to system `python3`
via `setup_webui.sh` and `setup_led_service.sh` when the venv is missing).

## Environment profiles (DEV/RPI)

Use a single entrypoint to create `.venv`:

```bash
python3 tools/bootstrap_env.py --target <dev|integration|rpi>
```

- `--target rpi`:
  - installs dependencies from `pyproject.toml` (`--editable ".[rpi]"`),
  - intended for Raspberry Pi runtime.
- `--target dev`:
  - installs developer dependencies from `requirements_dev.txt`.
- `--target integration`:
  - installs external integration test dependencies from
    `requirements_integration.txt` (including `paramiko`, `pysmb`).

The script writes a target marker to `.venv/.cnc_target` to reduce
environment-mismatch mistakes during test/tool execution.

## Configuration

Central configuration file:

```
/etc/cnc-control/cnc-control.env
```

The `tools/setup_system.sh` script copies the default `config/cnc-control.env.example` only if the destination file does not exist. After installation, fill in the values and save the file.

## Environment variables

- `CNC_USB_IMG` – path to the USB Mass Storage image.
- `CNC_MOUNT_POINT` – image mount point (G-code upload).
- `CNC_UPLOAD_DIR` – directory where WebUI writes uploaded files.

## Emergency Wi-Fi (Access Point)

On boot, `cnc-wifi-fallback.service` waits for a Wi-Fi connection handled by
NetworkManager. If no connection is established within the timeout, it starts
the Access Point mode (`cnc-ap.service`).

AP parameters:
- SSID: `CNC-SETUP`
- Password: `cnc-setup-1234` (WPA2-PSK)
- IP address: `192.168.50.1/24`
- DHCP range: `192.168.50.10-192.168.50.50`
- Interface: `wlan0`

The default Wi-Fi wait timeout is `45` seconds. You can change it via
`WIFI_CONNECT_TIMEOUT` in `/etc/cnc-control/cnc-control.env`.

Connecting to the AP allows Wi-Fi configuration and access to WebUI/SSH.

In AP mode the WebUI shows a cached list of Wi‑Fi networks captured just before
switching to AP, and also allows manual SSID/password entry. After confirmation
the AP is stopped automatically and the system connects to the chosen network.

Note:
- In AP mode scanning from the WebUI may be unavailable because `wlan0` is
  running as an access point. The list comes from a cache saved *before* AP.
- The scan cache is stored in `/tmp/cnc-wifi-scan.txt` by default
  (configurable via `WIFI_SCAN_CACHE`).

Return to normal Wi-Fi client mode:
- complete Wi-Fi setup (NetworkManager),
- reboot the system (after reboot the AP will not start if Wi-Fi is up).

## AP cycle test (no reboot)

The `tools/test_ap_cycle.sh` script switches `wlan0` into AP mode for a defined
time, then restores NetworkManager and reconnects Wi‑Fi.

Example with a longer AP duration (seconds):

```bash
sudo AP_TEST_TIME=300 tools/test_ap_cycle.sh
```

Environment parameters:
- `AP_TEST_TIME` – AP hold time in seconds (default `180`).
- `WIFI_CONNECT_TIMEOUT` – Wi‑Fi restore timeout (default `60`).
- `POLL_INTERVAL` – status polling interval (default `3`).
- `WIFI_SCAN_CACHE` – Wi‑Fi scan cache path (default `/tmp/cnc-wifi-scan.txt`).

The test script saves the scan cache right before switching to AP to mirror the
fallback behavior.

## PolicyKit (GUI restart)

The `tools/setup_system.sh` script installs a PolicyKit rule that allows the
WebUI user (`andrzej`) to run `systemctl restart cnc-webui.service` without a
password. For manual setup, copy
`systemd/polkit/50-cnc-webui-restart.rules` to `/etc/polkit-1/rules.d/`.

## Samba (smbd only, port 445)

Samba is intentionally configured in a minimal mode:

- Only `smbd.service` is enabled.
- `nmbd.service` (NetBIOS) is disabled.
- `samba-ad-dc.service` is not used (Raspberry Pi is not a domain controller).
- The server runs as a **standalone file server** and listens only on port 445.
- The `cnc_usb` share path is:
  - `CNC_MASTER_DIR` when `CNC_SHADOW_ENABLED=true` (aligned with WebUI),
  - `CNC_UPLOAD_DIR` (or `CNC_MOUNT_POINT` fallback) outside SHADOW mode.

### Why smbd only?

Disabling NetBIOS and AD-DC services shortens boot time and reduces the number of processes and
broadcast traffic on the network. This matters for CNC/embedded systems where fast readiness is
more important than full network browsing features.

### Performance and functional consequences

- Faster boot and less CPU/RAM usage (no `nmbd` or `samba-ad-dc`).
- No NetBIOS announcements: the share may not appear automatically in "Network Neighborhood".
  Connect directly:
  - Windows: `\\<RPI_IP>\cnc_usb`
  - macOS/Linux: `smb://<RPI_IP>/cnc_usb`

## Operating modes

- **USB (CNC)** – Raspberry Pi exposes the image as a USB mass storage device for the controller.
- **NET (UPLOAD)** – G-code upload over the network, without USB mode.

Modes are switched by the `usb_mode.sh` and `net_mode.sh` scripts.

## LED Status Indicator

The LED indicator runs as a dedicated `cnc-led.service` and uses:

- 3 WS2812/NeoPixel LEDs on `GPIO18`,
- `led_status.py` daemon,
- `led_status_cli.py` CLI,
- IPC via `/tmp/cnc_led_mode`.

Service installation:

```bash
chmod +x tools/setup_led_service.sh
sudo tools/setup_led_service.sh /home/andrzej/cnc-control
```

Mode mapping:

| Mode | Color | Behavior |
|---|---|---|
| `BOOT` | yellow `(255, 180, 0)` | steady |
| `USB` | red `(255, 0, 0)` | steady |
| `UPLOAD` | green `(0, 255, 0)` | steady |
| `AP` | blue `(0, 0, 255)` | blinking `1 Hz` |
| `ERROR` | red `(255, 0, 0)` | fast blink `3 Hz` |
| `IDLE` | dim white `(76, 76, 76)` | steady |

Safety:
- brightness limited to `0.3`,
- LEDs are turned off on service stop (e.g. `SIGTERM`),
- on systems without GPIO the daemon switches to fallback mode (no crash).

## Boot time optimization

The following choices shorten boot time and reduce unnecessary dependencies:

- **cloud-init** is disabled and masked (all units) because it is not used in this CNC setup
  and can add tens of seconds to boot time.
- **`nmbd.service` and `samba-ad-dc.service`** are disabled because they are not required
  for file transfer; only `smbd` remains (fewer processes and broadcasts).
- **`NetworkManager-wait-online.service`** is disabled and masked so boot does not wait
  for full network readiness (fast machine readiness matters more for CNC).
- **`cnc-usb.service`** starts *after* `multi-user.target` so it does not block the base
  system reaching the multi-user state during boot.

## Fast reboot – rules and delay causes

- Rebooting from WebUI in USB mode can be slow because the system must safely detach the USB gadget,
  wait for the controller to release the bus, and flush filesystem buffers.
- `network-online.target` slows boot when DHCP or networking is not ready; in CNC/embedded systems
  this is undesirable because fast machine readiness matters more than full network initialization.
  This project uses `network.target` only to avoid blocking startup.
- Disable `NetworkManager-wait-online.service`, because it can impose long timeouts during boot
  or reboot (especially without active DHCP/link):
  `sudo systemctl disable NetworkManager-wait-online.service`.
- `dwc2`, `g_mass_storage`, `g_ether` must not be enabled statically in `/boot/config.txt`
  or `/boot/cmdline.txt` — the gadget should be loaded dynamically only by `usb_mode.sh`.
- ZeroTier must not block boot; if its unit uses `After=network-online.target`, add an override
  with `network.target` (e.g. `sudo systemctl edit zerotier-one`):

```ini
[Unit]
After=network.target
Wants=network.target
```

Recommended reboot: switch to network mode (`net_mode.sh`), wait for the image to unmount,
then run `sudo systemctl reboot` (or `sudo reboot`) from SSH/terminal.

## Hidden system files

WebUI hides entries that start with `.` and common macOS system directories
(e.g. `.Spotlight-V100`, `.fseventsd`, `.Trashes`) in the file list view.
These entries are safely ignored in the presentation layer only and are not
removed from the storage.

## Diagnostics

```bash
systemctl cat cnc-webui
systemctl status cnc-webui
tr '\0' '\n' < /proc/<PID>/environ | grep CNC
```

Replace `<PID>` with the process ID from `systemctl status cnc-webui`.
