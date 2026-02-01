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

## Samba (smbd only, port 445)

Samba is intentionally configured in a minimal mode:

- Only `smbd.service` is enabled.
- `nmbd.service` (NetBIOS) is disabled.
- `samba-ad-dc.service` is not used (Raspberry Pi is not a domain controller).
- The server runs as a **standalone file server** and listens only on port 445.
- The shared path is `/mnt/cnc_usb` (share name `cnc_usb`).

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
