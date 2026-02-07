from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    send_file,
    after_this_request,
    jsonify,
)
import subprocess
import os
import tempfile
import json
import re
import shutil
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
UPLOAD_DIR = os.environ.get("CNC_UPLOAD_DIR")
if not UPLOAD_DIR:
    app.logger.error("Brak zmiennej CNC_UPLOAD_DIR. Upload i lista plikow beda niedostepne.")
NET_MODE_SCRIPT = os.environ.get(
    "CNC_NET_MODE_SCRIPT",
    os.path.join(REPO_ROOT, "net_mode.sh"),
)
USB_MODE_SCRIPT = os.environ.get(
    "CNC_USB_MODE_SCRIPT",
    os.path.join(REPO_ROOT, "usb_mode.sh"),
)
STATUS_SCRIPT = os.environ.get(
    "CNC_STATUS_SCRIPT",
    os.path.join(REPO_ROOT, "status.sh"),
)
CONTROL_REPO_DIR = os.environ.get(
    "CNC_CONTROL_REPO",
    "/home/andrzej/cnc-control",
)
WEBUI_LOG_PATH = os.environ.get(
    "CNC_WEBUI_LOG",
    "/var/log/cnc-control/webui.log",
)
WEBUI_SYSTEMD_UNIT = os.environ.get(
    "CNC_WEBUI_SYSTEMD_UNIT",
    "cnc-webui.service",
)
WEBUI_LOG_SINCE = os.environ.get(
    "CNC_WEBUI_LOG_SINCE",
    "24 hours ago",
)
APP_VERSION_FILE = os.path.join(CONTROL_REPO_DIR, ".app_version")
SEMVER_TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-+].*)?$")
HIDDEN_NAMES = {
    ".Spotlight-V100",
    ".fseventsd",
    ".Trashes",
}

HTML = """
<!doctype html>
<html>
<head>
<style>
.indicator {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-right: 6px;
}
.indicator--net { background-color: #3498db; }
.indicator--usb { background-color: #e67e22; }
.indicator--inactive { background-color: #bdc3c7; }

.mode-label {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-weight: 600;
}

.mode-net {
  color: #1f4f7a;
  background: #e3f2fd;
  border: 1px solid #90caf9;
}

.mode-usb {
  color: #8a4f0a;
  background: #fff3e0;
  border: 1px solid #ffcc80;
}

.mode-unknown {
  color: #555555;
  background: #f2f2f2;
  border: 1px solid #d6d6d6;
}

.mode-status {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}

.mode-status-hidden {
  display: none;
}

.mode-status-switching {
  color: #8a6d1d;
  background: #fff8e1;
  border: 1px solid #ffe082;
}

button {
  padding: 6px 12px;
  margin: 4px 0;
}

button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

body.ui-busy * {
  pointer-events: none;
}

body.ui-busy #loading-overlay,
body.ui-busy #loading-overlay * {
  pointer-events: auto;
}

#loading-overlay {
  position: fixed;
  inset: 0;
  display: none;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.45);
  z-index: 9999;
}

#loading-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 18px 22px;
  background: #ffffff;
  border-radius: 10px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
  min-width: 220px;
}

#loading-message {
  font-weight: 600;
}

#loading-timeout {
  display: none;
  font-size: 12px;
  color: #555555;
}

#loading-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid #d0d0d0;
  border-top-color: #2ecc71;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
</head>

<body>
<div id="loading-overlay" aria-hidden="true">
  <div id="loading-card" role="status" aria-live="polite">
    <div id="loading-spinner"></div>
    <div id="loading-message">Trwa wykonywanie operacji...</div>
    <div id="loading-timeout">Operacja trwa dłużej niż zwykle...</div>
  </div>
</div>

<h2>
  CNC USB Manager{% if app_version %} {{ app_version }}{% endif %}{% if app_description %} ({{ app_description }}){% endif %}
</h2>

<p>
  {% if page == 'system' %}
    <a href="/">Operacje CNC</a>
  {% else %}
    <a href="/system">System</a>
  {% endif %}
</p>

{% if message %}
<p><b>Status:</b> {{ message }}</p>
{% endif %}

{% if page != 'system' %}
<h3>Operacje CNC</h3>
<p><b>Tryb:</b>
  {% if mode == 'SIEĆ (UPLOAD)' %}
    <span id="mode-label" class="mode-label mode-net">{{ mode }}</span>
  {% elif mode == 'USB (CNC)' %}
    <span id="mode-label" class="mode-label mode-usb">{{ mode }}</span>
  {% else %}
    <span id="mode-label" class="mode-label mode-unknown">{{ mode }}</span>
  {% endif %}
  <span id="mode-switching" class="mode-status mode-status-hidden" aria-live="polite">PRZEŁĄCZANIE...</span>
</p>

<form action="/net" method="post">
  <span class="indicator {{ 'indicator--net' if mode == 'SIEĆ (UPLOAD)' else 'indicator--inactive' }}" data-mode-indicator="NET"></span>
  <button type="submit" data-mode-switch="NET">Tryb sieć (upload)</button>
</form>

<form action="/usb" method="post">
  <span class="indicator {{ 'indicator--usb' if mode == 'USB (CNC)' else 'indicator--inactive' }}" data-mode-indicator="USB"></span>
  <button type="submit" data-mode-switch="USB">Tryb USB (CNC)</button>
</form>

<hr>

<h3>Pliki CNC</h3>
<ul>
{% for f in files %}
  <li>{{ f }}</li>
{% endfor %}
</ul>

<hr>

<h3>Upload pliku</h3>
<form method=post enctype=multipart/form-data action="/upload">
  <input type=file name=file>
  <input type=submit value=Upload>
</form>
{% endif %}

{% if page == 'system' %}
<hr>

<h3>System</h3>
<form action="/restart" method="post">
  <input type="hidden" name="next" value="system">
  <button type="submit">Restart</button>
</form>

<div>
  <button
    type="button"
    id="restart-gui-button"
    title="Niedostępne w trybie USB"
    disabled
  >
    🔄 Restart GUI
  </button>
</div>

<form action="/poweroff" method="post">
  <input type="hidden" name="next" value="system">
  <button type="submit">Power off</button>
</form>

<form action="/git-pull" method="post">
  <input type="hidden" name="next" value="system">
  <button type="submit">Aktualizacja</button>
</form>

<form action="/git-pull-plain" method="post">
  <input type="hidden" name="next" value="system">
  <button type="submit">Git pull</button>
</form>

<form action="/download-log" method="get">
  <input type="hidden" name="next" value="system">
  <button type="submit">Pobierz log</button>
</form>
{% endif %}

<script>
  const overlay = document.getElementById("loading-overlay");
  const timeoutMessage = document.getElementById("loading-timeout");
  const messageLabel = document.getElementById("loading-message");
  let busy = false;
  let timeoutId = null;

  function setControlsDisabled(disabled) {
    const controls = document.querySelectorAll("button, input, select, textarea");
    controls.forEach((control) => {
      if (disabled) {
        if (!control.hasAttribute("data-prev-disabled")) {
          control.setAttribute("data-prev-disabled", control.disabled ? "1" : "0");
        }
        control.disabled = true;
      } else {
        const prev = control.getAttribute("data-prev-disabled");
        if (prev !== null) {
          control.disabled = prev === "1";
          control.removeAttribute("data-prev-disabled");
        } else {
          control.disabled = false;
        }
      }
    });
  }

  function setBusy(state, text) {
    busy = state;
    if (state) {
      if (text) {
        messageLabel.textContent = text;
      } else {
        messageLabel.textContent = "Trwa wykonywanie operacji...";
      }
      overlay.style.display = "flex";
      overlay.setAttribute("aria-hidden", "false");
      document.body.classList.add("ui-busy");
      setControlsDisabled(true);
      timeoutMessage.style.display = "none";
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      timeoutId = setTimeout(() => {
        if (busy) {
          timeoutMessage.style.display = "block";
        }
      }, 10000);
      return;
    }

    overlay.style.display = "none";
    overlay.setAttribute("aria-hidden", "true");
    document.body.classList.remove("ui-busy");
    setControlsDisabled(false);
    timeoutMessage.style.display = "none";
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function extractFilename(disposition) {
    if (!disposition) {
      return "cnc-log.log";
    }
    const match = disposition.match(/filename="?([^"]+)"?/i);
    if (match && match[1]) {
      return match[1];
    }
    return "cnc-log.log";
  }

  function updateRestartGuiButton(mode) {
    const button = document.getElementById("restart-gui-button");
    if (!button) {
      return;
    }
    const isUsb = mode === "USB";
    button.disabled = isUsb;
    if (isUsb) {
      button.title = "Niedostępne w trybie USB";
    } else {
      button.removeAttribute("title");
    }
  }

  async function restartGui() {
    const button = document.getElementById("restart-gui-button");
    if (!button || button.disabled || busy) {
      return;
    }
    setBusy(true, "Restarting GUI…");
    try {
      const response = await fetch("/api/restart-gui", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) {
        let message = "Nie udało się zrestartować GUI.";
        try {
          const payload = await response.json();
          if (payload && payload.error) {
            message = payload.error;
          } else {
            message = "Błąd HTTP: " + response.status;
          }
        } catch (error) {
          message = "Błąd HTTP: " + response.status;
        }
        throw new Error(message);
      }
      setTimeout(() => {
        window.location.reload();
      }, 5000);
    } catch (error) {
      setBusy(false);
      alert(error.message || "Nie udało się zrestartować GUI.");
    }
  }

  async function runAction(request) {
    if (busy) {
      return;
    }
    let replaced = false;
    setBusy(true);
    try {
      const response = await fetch(request);
      const contentType = response.headers.get("content-type") || "";
      const disposition = response.headers.get("content-disposition") || "";
      const isAttachment = disposition.toLowerCase().includes("attachment");
      const isHtml = contentType.toLowerCase().includes("text/html");

      if (isAttachment || !isHtml) {
        const blob = await response.blob();
        const filename = extractFilename(disposition);
        downloadBlob(blob, filename);
      } else {
        const html = await response.text();
        replaced = true;
        setBusy(false);
        document.open();
        document.write(html);
        document.close();
        return;
      }

      if (!response.ok) {
        alert("Błąd HTTP: " + response.status);
      }
    } catch (error) {
      alert("Błąd połączenia: " + error);
    } finally {
      if (!replaced) {
        setBusy(false);
      }
    }
  }

  function buildRequest(form) {
    const action = form.action || window.location.href;
    const method = (form.method || "GET").toUpperCase();
    if (method === "GET") {
      const url = new URL(action, window.location.href);
      const formData = new FormData(form);
      for (const [key, value] of formData.entries()) {
        if (typeof value === "string") {
          url.searchParams.append(key, value);
        }
      }
      return new Request(url.toString(), {
        method: "GET",
        credentials: "same-origin",
      });
    }

    return new Request(action, {
      method: method,
      body: new FormData(form),
      credentials: "same-origin",
    });
  }

  const MODE_LABELS = {
    NET: "SIEĆ (UPLOAD)",
    USB: "USB (CNC)",
  };
  const MODE_CLASS = {
    NET: "mode-net",
    USB: "mode-usb",
  };
  const INDICATOR_CLASS = {
    NET: "indicator--net",
    USB: "indicator--usb",
  };

  function applyMode(mode) {
    const label = MODE_LABELS[mode];
    if (!label) {
      return;
    }
    const modeLabel = document.getElementById("mode-label");
    if (modeLabel) {
      modeLabel.textContent = label;
      modeLabel.classList.remove("mode-net", "mode-usb", "mode-unknown");
      modeLabel.classList.add(MODE_CLASS[mode] || "mode-unknown");
    }
    updateRestartGuiButton(mode);
    const indicators = document.querySelectorAll("[data-mode-indicator]");
    indicators.forEach((indicator) => {
      const indicatorMode = indicator.getAttribute("data-mode-indicator");
      const isActive = indicatorMode === mode;
      indicator.classList.remove("indicator--net", "indicator--usb", "indicator--inactive");
      if (isActive) {
        indicator.classList.add(INDICATOR_CLASS[mode] || "indicator--inactive");
      } else {
        indicator.classList.add("indicator--inactive");
      }
    });
  }

  function applySwitching(switching) {
    if (switching !== true && switching !== false) {
      return;
    }
    const statusLabel = document.getElementById("mode-switching");
    if (statusLabel) {
      if (switching) {
        statusLabel.classList.remove("mode-status-hidden");
        statusLabel.classList.add("mode-status-switching");
      } else {
        statusLabel.classList.add("mode-status-hidden");
        statusLabel.classList.remove("mode-status-switching");
      }
    }
    const buttons = document.querySelectorAll("[data-mode-switch]");
    buttons.forEach((button) => {
      button.disabled = switching;
    });
  }

  async function pollStatus() {
    try {
      const response = await fetch("/api/status", {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      if (payload && payload.mode) {
        applyMode(payload.mode);
      }
      if (payload && "switching" in payload) {
        applySwitching(payload.switching);
      }
    } catch (error) {
      // PL: Ignorujemy błędy odpytywania statusu, aby nie zakłócać UI.
      // EN: Ignore polling errors to avoid disrupting the UI.
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const forms = document.querySelectorAll("form");
    forms.forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        if (busy) {
          return;
        }
        const request = buildRequest(form);
        runAction(request);
      });
    });

    const restartGuiButton = document.getElementById("restart-gui-button");
    if (restartGuiButton) {
      restartGuiButton.addEventListener("click", () => {
        restartGui();
      });
    }

    if (document.getElementById("mode-label") || restartGuiButton) {
      pollStatus();
      setInterval(pollStatus, 2000);
    }
  });
</script>

</body>
</html>
"""

def is_usb_mode():
    return subprocess.call("lsmod | grep -q g_mass_storage", shell=True) == 0


def is_hidden_file(name):
    return name.startswith(".") or name in HIDDEN_NAMES


def log_webui_event(message):
    timestamp = datetime.now().isoformat(timespec="seconds")
    log_line = f"[{timestamp}] {message}\n"
    try:
        log_dir = os.path.dirname(WEBUI_LOG_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(WEBUI_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(log_line)
    except OSError:
        app.logger.warning("Nie mozna zapisac do CNC_WEBUI_LOG: %s", WEBUI_LOG_PATH)


def parse_status_mode(output):
    for line in output.splitlines():
        if "Tryb pracy:" not in line:
            continue
        value = line.split("Tryb pracy:", 1)[1].strip()
        value_norm = value.casefold()
        if value_norm.startswith("usb"):
            return "USB"
        if value_norm.startswith("sieć") or value_norm.startswith("siec"):
            return "NET"
    return None


def parse_status_mount_point(output):
    for line in output.splitlines():
        if not line.startswith("Punkt montowania:"):
            continue
        value = line.split("Punkt montowania:", 1)[1].strip()
        return value or None
    return None


def is_mount_active(mount_point):
    if not mount_point:
        return None
    result = subprocess.run(
        ["mount"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        app.logger.warning("Nie mozna odczytac listy montowan (rc=%s).", result.returncode)
        return None
    needle = f" on {mount_point} "
    for line in (result.stdout or "").splitlines():
        if needle in line:
            return True
    return False


def is_samba_active():
    if not shutil.which("systemctl"):
        app.logger.warning("Brak systemctl - nie mozna sprawdzic smbd.")
        return None
    result = subprocess.run(
        ["systemctl", "is-active", "smbd.service"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and (result.stdout or "").strip() == "active":
        return True
    if result.returncode != 0 and (result.stdout or "").strip() == "unknown":
        app.logger.warning("smbd.service nie istnieje w systemd.")
    return False


def run_git_command(args, cwd, label):
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    log_webui_event(f"{label} (rc={result.returncode}) stdout='{stdout}' stderr='{stderr}'")
    return result, stdout, stderr


def read_app_version():
    if not os.path.isfile(APP_VERSION_FILE):
        return None
    try:
        with open(APP_VERSION_FILE, "r", encoding="utf-8") as version_file:
            data = json.load(version_file)
        version = data.get("version")
        description = data.get("description", "")
        if not version:
            return None
        return {"version": version, "description": description or ""}
    except (OSError, json.JSONDecodeError):
        return None


def write_app_version(version, description):
    data = {"version": version, "description": description or ""}
    with open(APP_VERSION_FILE, "w", encoding="utf-8") as version_file:
        json.dump(data, version_file, ensure_ascii=True, indent=2)
        version_file.write("\n")


def get_fallback_version():
    result, stdout, stderr = run_git_command(
        ["git", "describe", "--tags", "--dirty", "--always"],
        CONTROL_REPO_DIR,
        "git describe --tags --dirty --always",
    )
    if result.returncode != 0:
        app.logger.error("Blad git describe: %s", stderr)
        return {"version": None, "description": ""}
    return {"version": stdout, "description": ""}


def get_app_version():
    version_data = read_app_version()
    if version_data:
        return version_data
    return get_fallback_version()


def get_latest_semver_tag():
    result, stdout, stderr = run_git_command(
        ["git", "tag", "--sort=-v:refname"],
        CONTROL_REPO_DIR,
        "git tag --sort=-v:refname",
    )
    if result.returncode != 0:
        return None, f"Blad git tag: {stderr or stdout}"
    tags = [line.strip() for line in stdout.splitlines() if line.strip()]
    for tag in tags:
        if SEMVER_TAG_RE.match(tag):
            return tag, None
    return None, "Brak tagow semver w repozytorium"


def get_tag_description(tag):
    result, stdout, stderr = run_git_command(
        ["git", "tag", "-l", tag, "-n99"],
        CONTROL_REPO_DIR,
        f"git tag -l {tag} -n99",
    )
    if result.returncode != 0:
        return None, f"Blad pobierania opisu taga: {stderr or stdout}"
    first_line = ""
    for line in stdout.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    if not first_line:
        return "", None
    if first_line.startswith(tag):
        description = first_line[len(tag):].strip()
        return description, None
    return "", None


def is_repo_dirty():
    result, stdout, stderr = run_git_command(
        ["git", "status", "--porcelain"],
        CONTROL_REPO_DIR,
        "git status --porcelain",
    )
    if result.returncode != 0:
        return None, f"Blad git status: {stderr or stdout}"
    return bool(stdout.strip()), None


def redirect_to_next(message=None):
    next_page = request.form.get("next") or request.args.get("next")
    if next_page == "system":
        if message:
            return redirect(url_for("system", msg=message))
        return redirect(url_for("system"))
    if message:
        return redirect(url_for("index", msg=message))
    return redirect(url_for("index"))


@app.route("/")
def index():
    usb = is_usb_mode()
    mode = "USB (CNC)" if usb else "SIEĆ (UPLOAD)"
    files = []
    message = request.args.get("msg")
    version_data = get_app_version()
    if not UPLOAD_DIR and not message:
        message = "Brak konfiguracji CNC_UPLOAD_DIR"
    if not usb and UPLOAD_DIR and os.path.isdir(UPLOAD_DIR):
        files = [name for name in os.listdir(UPLOAD_DIR) if not is_hidden_file(name)]
    return render_template_string(
        HTML,
        page="main",
        mode=mode,
        files=files,
        message=message,
        app_version=version_data.get("version"),
        app_description=version_data.get("description"),
    )

@app.route("/system")
def system():
    message = request.args.get("msg")
    version_data = get_app_version()
    return render_template_string(
        HTML,
        page="system",
        mode=None,
        files=[],
        message=message,
        app_version=version_data.get("version"),
        app_description=version_data.get("description"),
    )

@app.route("/net", methods=["POST"])
def net():
    subprocess.call([NET_MODE_SCRIPT])
    return redirect(url_for("index"))

@app.route("/usb", methods=["POST"])
def usb():
    subprocess.call([USB_MODE_SCRIPT])
    return redirect(url_for("index"))

@app.route("/api/status", methods=["GET"])
def api_status():
    result = subprocess.run(
        [STATUS_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    mode = parse_status_mode(stdout)
    mount_point = parse_status_mount_point(stdout)
    if not mode:
        app.logger.warning(
            "Nie rozpoznano trybu z status.sh (rc=%s). stdout='%s' stderr='%s'",
            result.returncode,
            stdout.strip(),
            stderr.strip(),
        )
        return jsonify({"mode": None, "error": "Brak trybu w status.sh"}), 500
    usb_gadget = mode == "USB"
    img_mounted = is_mount_active(mount_point)
    samba_active = is_samba_active()
    switching = None
    if img_mounted is not None:
        switching = usb_gadget and img_mounted
    return jsonify(
        {
            "mode": mode,
            "usb_gadget": usb_gadget,
            "samba": samba_active,
            "mount_point": mount_point,
            "img_mounted": img_mounted,
            "switching": switching,
        }
    )

@app.route("/api/restart-gui", methods=["POST"])
def api_restart_gui():
    try:
        status_result = subprocess.run(
            [STATUS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout status.sh"}), 500
    except OSError:
        return jsonify({"error": "Nie można uruchomić status.sh"}), 500

    stdout = status_result.stdout or ""
    stderr = status_result.stderr or ""
    if status_result.returncode != 0:
        app.logger.warning(
            "status.sh zakonczony bledem (rc=%s). stdout='%s' stderr='%s'",
            status_result.returncode,
            stdout.strip(),
            stderr.strip(),
        )
        return jsonify({"error": "Błąd status.sh"}), 500

    mode = parse_status_mode(stdout)
    if not mode:
        app.logger.warning(
            "Nie rozpoznano trybu z status.sh. stdout='%s' stderr='%s'",
            stdout.strip(),
            stderr.strip(),
        )
        return jsonify({"error": "Brak trybu w status.sh"}), 500

    if mode == "USB":
        return jsonify({"error": "GUI restart disabled in USB mode"}), 409

    if mode != "NET":
        return jsonify({"error": "Nieznany tryb pracy"}), 500

    if not shutil.which("systemctl"):
        return jsonify({"error": "Brak systemctl"}), 500

    try:
        restart_result = subprocess.run(
            ["systemctl", "restart", "cnc-webui.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout restartu GUI"}), 500
    except OSError:
        return jsonify({"error": "Nie można uruchomić systemctl"}), 500

    if restart_result.returncode != 0:
        detail = (restart_result.stderr or restart_result.stdout or "").strip()
        message = "Błąd restartu GUI"
        if detail:
            message = f"{message}: {detail}"
        return jsonify({"error": message}), 500

    return jsonify({"ok": True})

@app.route("/upload", methods=["POST"])
def upload():
    if not UPLOAD_DIR:
        return redirect(url_for("index", msg="Brak konfiguracji CNC_UPLOAD_DIR"))

    if is_usb_mode():
        return redirect(url_for("index", msg="Tryb USB: upload niedostępny"))

    if "file" not in request.files:
        return redirect(url_for("index", msg="Brak pliku w żądaniu"))

    f = request.files["file"]
    if not f or f.filename == "":
        return redirect(url_for("index", msg="Nie wybrano pliku"))

    safe_name = secure_filename(f.filename)
    if safe_name == "":
        return redirect(url_for("index", msg="Nieprawidłowa nazwa pliku"))

    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        target_path = os.path.join(UPLOAD_DIR, safe_name)
        f.save(target_path)
    except Exception:
        return redirect(url_for("index", msg="Błąd zapisu pliku"))

    return redirect(url_for("index", msg="Upload OK"))

@app.route("/restart", methods=["POST"])
def restart():
    subprocess.call(["sudo", "reboot"])
    return redirect_to_next()

@app.route("/poweroff", methods=["POST"])
def poweroff():
    subprocess.call(["sudo", "poweroff"])
    return redirect_to_next()

@app.route("/git-pull", methods=["POST"])
def git_pull():
    dirty, error = is_repo_dirty()
    if error:
        return redirect_to_next(error)
    if dirty:
        return redirect_to_next("Repozytorium ma niezacommitowane zmiany")

    fetch_result, _, fetch_err = run_git_command(
        ["git", "fetch", "--tags"],
        CONTROL_REPO_DIR,
        "git fetch --tags",
    )
    if fetch_result.returncode != 0:
        return redirect_to_next(f"Blad git fetch: {fetch_err}")

    tag, tag_error = get_latest_semver_tag()
    if tag_error:
        return redirect_to_next(tag_error)
    if not tag:
        return redirect_to_next("Brak tagow w repozytorium")

    description, description_error = get_tag_description(tag)
    if description_error:
        return redirect_to_next(description_error)

    checkout_result, _, checkout_err = run_git_command(
        ["git", "checkout", tag],
        CONTROL_REPO_DIR,
        f"git checkout {tag}",
    )
    if checkout_result.returncode != 0:
        return redirect_to_next(f"Blad git checkout: {checkout_err}")

    try:
        write_app_version(tag, description)
    except OSError:
        return redirect_to_next("Blad zapisu .app_version")

    return redirect_to_next(f"Zaktualizowano do {tag}")

@app.route("/git-pull-plain", methods=["POST"])
def git_pull_plain():
    result, stdout, stderr = run_git_command(
        ["git", "pull"],
        CONTROL_REPO_DIR,
        "git pull",
    )
    if result.returncode != 0:
        return redirect_to_next(stderr or stdout or "Blad git pull")
    return redirect_to_next(stdout or "Git pull OK")

@app.route("/download-log", methods=["GET"])
def download_log():
    try:
        if os.path.isfile(WEBUI_LOG_PATH):
            return send_file(WEBUI_LOG_PATH, as_attachment=True)

        # PL: Pobranie logu z systemd (journalctl) do pliku tymczasowego.
        # EN: Fetch systemd log (journalctl) into a temporary file.
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                WEBUI_SYSTEMD_UNIT,
                "-b",
                "--since",
                WEBUI_LOG_SINCE,
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return redirect_to_next("Brak logu w systemd")

        tmp_file = tempfile.NamedTemporaryFile(
            prefix="cnc-webui-",
            suffix=".log",
            delete=False,
        )
        with tmp_file:
            tmp_file.write(result.stdout.encode("utf-8"))

        @after_this_request
        def cleanup_temp_file(response):
            try:
                os.remove(tmp_file.name)
            except OSError:
                pass
            return response

        return send_file(tmp_file.name, as_attachment=True)
    except Exception:
        return redirect_to_next("Błąd pobierania logu")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
