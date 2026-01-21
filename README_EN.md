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

## ▶️ Running the Project

```bash
python main.py
```

Detailed runtime parameters are documented directly in the source code.

---

## ⌨️ Shortcut Commands (CLI)

To run modes with single commands (`usb_mode`, `net_mode`, `status`), install shortcuts:

```bash
chmod +x tools/setup_commands.sh
./tools/setup_commands.sh
```

The script creates links to `usb_mode.sh`, `net_mode.sh`, `status.sh` and, if needed, adds `~/.local/bin` to `PATH` (in `~/.bashrc`).

---

## 📁 Repository Structure

```
cnc-control/
├── AGENTS.md
├── README.md
├── README_EN.md
├── net_mode.sh
├── status.sh
├── usb_mode.sh
├── tools/
│   ├── setup_commands.sh
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
| `net_mode.sh` | Switches network mode (host/gadget). |
| `status.sh` | Quick status view of the system/connections. |
| `usb_mode.sh` | Switches USB mode for Raspberry Pi. |
| `tools/` | Helper scripts for environment setup. |
| `tools/setup_commands.sh` | Installs shortcut commands `usb_mode`, `net_mode`, `status`. |
| `tools/setup_nmtui.sh` | Installs and launches `nmtui`. |
| `tools/setup_zerotier.sh` | Configures the ZeroTier client. |
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
