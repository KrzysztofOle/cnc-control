# System Installation

## System requirements

- Raspberry Pi running a systemd-based Linux (e.g. Raspberry Pi OS Lite)
- Python 3 (required by WebUI)
- Git
- Root access (sudo)
- Repository located at `/home/andrzej/cnc-control` (required by the systemd unit)

## Step-by-step installation

```bash
git clone https://github.com/<your-user>/cnc-control.git /home/andrzej/cnc-control
cd /home/andrzej/cnc-control
sudo ./tools/setup_system.sh
```

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

## Operating modes

- **USB (CNC)** – Raspberry Pi exposes the image as a USB mass storage device for the controller.
- **NET (UPLOAD)** – G-code upload over the network, without USB mode.

Modes are switched by the `usb_mode.sh` and `net_mode.sh` scripts.

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
