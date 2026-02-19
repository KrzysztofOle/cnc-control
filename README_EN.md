# 🛠️ CNC Control – Raspberry Pi Integration with RichAuto A11E

## 📌 Project Overview

This repository contains code and auxiliary configuration for integrating the **RichAuto A11E (DSP) CNC controller** with **Raspberry Pi**.  
The main objective is to enhance CNC machine operation by:

- automating selected tasks,
- supporting G-code file transfer,
- extending controller usability without modifying its firmware,
- leveraging a low-cost and energy-efficient SBC platform.

The project is developed as a **practical workshop-oriented solution**, not as a firmware replacement.

---

## 🧩 Scope of Functionality

- 📂 G-code file management
- 🔌 Communication via USB devices / local network
- ⚙️ Helper scripts for Raspberry Pi
- 📶 Emergency Wi-Fi mode (AP `CNC-SETUP`) for network setup
- 🧪 Hardware compatibility testing (power, peripherals)

> ⚠️ The project **does not interfere** with RichAuto controller PLC logic.  
> It acts solely as a supporting system.

---

## 🖥️ Hardware Requirements

| Component | Requirement |
|---------|------------|
| CNC Controller | RichAuto A11 / A11E |
| SBC | Raspberry Pi Zero / Zero 2 W / 3B+ |
| Power Supply | 5 V (minimum 2 A recommended) |
| Storage | microSD ≥ 8 GB |
| Network | Wi-Fi or Ethernet (USB adapter) |

---

## 🧰 Software Requirements

- 🐧 Linux (Raspberry Pi OS Lite recommended)
- 🐍 Python 3.9+
- 📦 pip / venv
- 🔧 Git

Optional:
- Samba / FTP
- SSH

---

## 🚀 Installation

```bash
git clone https://github.com/<your-user>/cnc-control.git
cd cnc-control

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## 🧱 System installation

System setup after a fresh `git clone` is described in `docs/INSTALL_EN.md`.

### Quick SSH bootstrap (recommended)

Target installation flow:

1. Download only `bootstrap_cnc.sh` from the repository.
2. Connect to Raspberry Pi over SSH and upload the script.
3. Run the script and let it perform the full setup.

On your local machine:

```bash
curl -fsSL -o bootstrap_cnc.sh \
  https://raw.githubusercontent.com/KrzysztofOle/cnc-control/main/tools/bootstrap_cnc.sh
chmod +x bootstrap_cnc.sh
scp bootstrap_cnc.sh pi@<RPI_IP>:/home/pi/bootstrap_cnc.sh
```

On Raspberry Pi:

```bash
ssh pi@<RPI_IP>
chmod +x ~/bootstrap_cnc.sh
~/bootstrap_cnc.sh
```

The script automatically:
- updates the system (`apt update/upgrade`),
- installs dependencies,
- clones/updates the `cnc-control` repository over HTTPS,
- runs `setup_system.sh`, `setup_commands.sh`, `setup_webui.sh`, `setup_usb_service.sh`, `setup_led_service.sh`.

Optional user and repo directory override:

```bash
CNC_INSTALL_USER=pi CNC_REPO_DIR=/home/pi/cnc-control ~/bootstrap_cnc.sh
```

---

## ▶️ Running the Project

```bash
python main.py
```

Detailed runtime parameters are documented directly in the source code.

---

## 🧾 Versioning

Rule: **Git tag = application version**. Use **annotated tags**.

Example:

```bash
git tag -a v0.1.14 -m "zerotier"
git push origin v0.1.10
```

The tag description is displayed in the WebUI.

---

## ⌨️ Shortcut Commands (CLI)

To run modes with single commands (`usb_mode`, `net_mode`, `status`), install shortcuts:

```bash
chmod +x tools/setup_commands.sh
./tools/setup_commands.sh
```

The script creates links to `usb_mode.sh`, `net_mode.sh`, `status.sh` and, if needed, adds `~/.local/bin` to `PATH` (in `~/.bashrc` and `~/.zshrc`).

---

## 🧩 systemd Services (Autostart)

To start webui and USB mode automatically after boot, use:

```bash
chmod +x tools/setup_webui.sh
sudo tools/setup_webui.sh ~/cnc-control

chmod +x tools/setup_usb_service.sh
sudo tools/setup_usb_service.sh ~/cnc-control

chmod +x tools/setup_led_service.sh
sudo tools/setup_led_service.sh ~/cnc-control
```

The scripts create `cnc-webui.service`, `cnc-usb.service`, and `cnc-led.service`, enable autostart, and restart the services.

---

## LED Status Indicator

- Hardware: 3x WS2812/NeoPixel on `GPIO18`
- Brightness: `BRIGHTNESS=0.3` (power draw limit)
- Logic: all 3 LEDs always use the same color and blink in full sync
- IPC: `/tmp/cnc_led_mode` (written by `led_status_cli.py`, monitored by `led_status.py`)
- Service: `cnc-led.service`

Mode mapping:

| Mode | Color | Behavior |
|---|---|---|
| `BOOT` | yellow `(255, 180, 0)` | steady |
| `USB` | red `(255, 0, 0)` | steady |
| `UPLOAD` | green `(0, 255, 0)` | steady |
| `AP` | blue `(0, 0, 255)` | blinking `1 Hz` |
| `ERROR` | red `(255, 0, 0)` | fast blink `3 Hz` |
| `IDLE` | dim white `(76, 76, 76)` | steady |

---

## 🌐 Wi-Fi Configuration (WebUI)

The WebUI provides a simple Wi-Fi configuration based on NetworkManager (`nmcli`).

Features:
- quick switching to a saved profile without re-entering the password,
- automatic password field lock for networks with a saved profile,
- saved profile removal directly from WebUI,
- `AP block` switch (effective only until next reboot),
- global AP lock controlled by `CNC_AP_ENABLED` (system lock),
- automatic fallback to the previous profile when a new connection attempt fails.

Requirements:
- NetworkManager installed and running (service `NetworkManager`)
- sudo rules for `nmcli` (no password) for the user running WebUI
- run WebUI as a regular user (not root)
- Wi-Fi passwords are not stored by the app or scripts

Minimal sudoers (file `/etc/sudoers.d/cnc-wifi`):

```bash
andrzej ALL=(root) NOPASSWD: /usr/bin/nmcli *
andrzej ALL=(root) NOPASSWD: /usr/bin/systemctl stop cnc-ap.service
```

Helper script used by WebUI: `tools/wifi_control.sh`.

### AP Mode Lock

The `CNC_AP_ENABLED` variable defaults to `false`.

With `CNC_AP_ENABLED=false`:
- the UI shows badge `AP: DISABLED (SYSTEM LOCK)`,
- AP controls remain visible but disabled (greyed out),
- backend rejects AP state change via API with `403` and:
  `AP mode disabled by system configuration`.

AP logic stays in the codebase and can be re-enabled by setting
`CNC_AP_ENABLED=true`.

---

## ⚡ Fast reboot – rules and delay causes

- `network-online.target` slows boot when DHCP or networking is not ready; in CNC/embedded systems
  this is undesirable because fast machine readiness matters more than full network initialization.
  This project uses `network.target` only to avoid blocking startup.
- Disable `NetworkManager-wait-online.service`, because it can impose long timeouts during boot
  or reboot (especially without active DHCP/link):
  `sudo systemctl disable NetworkManager-wait-online.service`.

---

## ⚙️ System Configuration and Environment Variables

Configuration is centrally managed via:

```
/etc/cnc-control/cnc-control.env
```

This file is loaded by systemd (`EnvironmentFile=`), mode scripts (`net_mode.sh`, `usb_mode.sh`), and WebUI (`webui/app.py`). Missing file or required variables cause explicit errors.

Quick start:

```bash
sudo mkdir -p /etc/cnc-control
sudo cp config/cnc-control.env.example /etc/cnc-control/cnc-control.env
sudo nano /etc/cnc-control/cnc-control.env
```

Required variables (no defaults):

| Variable | Description | Default | Usage |
|---|---|---|---|
| `CNC_USB_IMG` | Path to USB Mass Storage image | none (required) | `net_mode.sh`, `usb_mode.sh` |
| `CNC_MOUNT_POINT` | Image mount point (G-code upload) | none (required) | `net_mode.sh`, `usb_mode.sh` |
| `CNC_UPLOAD_DIR` | WebUI upload directory | none (required) | `webui/app.py` |

Optional variables:

| Variable | Description | Default | Usage |
|---|---|---|---|
| `CNC_NET_MODE_SCRIPT` | Path to network mode script | `<repo>/net_mode.sh` | `webui/app.py` |
| `CNC_USB_MODE_SCRIPT` | Path to USB mode script | `<repo>/usb_mode.sh` | `webui/app.py` |
| `CNC_CONTROL_REPO` | Repository path (for `git pull`) | `/home/andrzej/cnc-control` | `webui/app.py` |
| `CNC_WEBUI_LOG` | WebUI log file path | `/var/log/cnc-control/webui.log` | `webui/app.py` |
| `CNC_WEBUI_SYSTEMD_UNIT` | systemd unit name for webui | `cnc-webui.service` | `webui/app.py` |
| `CNC_WEBUI_LOG_SINCE` | Time range for `journalctl` (e.g. `24 hours ago`) | `24 hours ago` | `webui/app.py` |
| `CNC_AP_BLOCK_FLAG` | Path to temporary AP block flag file | `/dev/shm/cnc-ap-blocked.flag` | `webui/app.py`, `tools/wifi_fallback.sh` |
| `CNC_AP_ENABLED` | Global AP switch (`true`/`false`) | `false` | `webui/app.py` |
| `CNC_USB_MOUNT` | Legacy: USB mount point | none | `net_mode.sh`, `usb_mode.sh`, `status.sh` |

---

## 📁 Repository Structure

```
cnc-control/
├── AGENTS.md
├── README.md
├── README_EN.md
├── config/
├── led_status.py
├── led_status_cli.py
├── net_mode.sh
├── status.sh
├── usb_mode.sh
├── tools/
│   ├── setup_commands.sh
│   ├── setup_led_service.sh
│   ├── setup_usb_service.sh
│   ├── setup_webui.sh
│   ├── setup_nmtui.sh
│   └── setup_zerotier.sh
└── webui/
    └── app.py
```

### 📄 Files and Directories

| File/Directory | Description |
|---|---|
| `AGENTS.md` | Collaboration and documentation rules for the project. |
| `README.md` | Primary documentation in Polish. |
| `README_EN.md` | Supporting documentation in English. |
| `config/` | Example configuration files. |
| `config/cnc-control.env.example` | Example central configuration (EnvironmentFile). |
| `led_status.py` | WS2812 LED daemon (GPIO18) monitoring IPC and driving LED state. |
| `led_status_cli.py` | CLI for LED mode IPC writes (`/tmp/cnc_led_mode`). |
| `net_mode.sh` | Switches network mode (host/gadget). |
| `status.sh` | Quick status view of the system/connections. |
| `usb_mode.sh` | Switches USB mode for Raspberry Pi. |
| `tools/` | Helper scripts for environment setup. |
| `tools/setup_commands.sh` | Installs shortcut commands `usb_mode`, `net_mode`, `status`. |
| `tools/setup_led_service.sh` | Configures `cnc-led.service` for `led_status.py`. |
| `tools/setup_usb_service.sh` | Configures `cnc-usb.service` for `usb_mode.sh`. |
| `tools/setup_webui.sh` | Configures `cnc-webui.service` for webui. |
| `tools/setup_nmtui.sh` | Installs and launches `nmtui`. |
| `tools/setup_zerotier.sh` | Configures the ZeroTier client. |
| `tools/wifi_control.sh` | Helper script for Wi-Fi scan/connect (`nmcli`). |
| `webui/` | Simple web UI for tool access. |
| `webui/app.py` | Web application (server) for webui. |

---

## ⚠️ Limitations and Notes

- ❌ no direct integration with ctrlX PLC Engineering
- ❌ no RichAuto firmware modifications
- ⚠️ limited USB current output on A11E controller

---

## 🧭 Future Development

- 📊 machine operation monitoring
- 🌐 web-based interface
- 🔄 automated G-code synchronization
- 🧾 event and operation logging

---

## 📄 License

MIT License

---

## 👤 Author

Krzysztof  
Python • OpenCV • CNC • Automation

---

## 💬 Final Notes

When using this project on a real CNC machine, always ensure:
- emergency stop access,
- manual override capability,
- testing without a cutting tool first.
