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
