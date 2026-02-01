from flask import (
    Flask,
    request,
    redirect,
    url_for,
    render_template_string,
    send_file,
    after_this_request,
)
import subprocess
import os
import tempfile
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
.green { background-color: #2ecc71; }
.gray  { background-color: #bdc3c7; }

button {
  padding: 6px 12px;
  margin: 4px 0;
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

<h2>CNC USB Manager</h2>

{% if message %}
<p><b>Status:</b> {{ message }}</p>
{% endif %}

<p><b>Tryb:</b> {{ mode }}</p>

<form action="/net" method="post">
  <span class="indicator {{ 'green' if mode == 'SIEĆ (UPLOAD)' else 'gray' }}"></span>
  <button type="submit">Tryb sieć (upload)</button>
</form>

<form action="/usb" method="post">
  <span class="indicator {{ 'green' if mode == 'USB (CNC)' else 'gray' }}"></span>
  <button type="submit">Tryb USB (CNC)</button>
</form>

<hr>

<h3>System</h3>
<form action="/restart" method="post">
  <button type="submit">Restart</button>
</form>

<form action="/poweroff" method="post">
  <button type="submit">Power off</button>
</form>

<form action="/git-pull" method="post">
  <button type="submit">Git pull (aktualizacja)</button>
</form>

<form action="/download-log" method="get">
  <button type="submit">Pobierz log</button>
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
  });
</script>

</body>
</html>
"""

def is_usb_mode():
    return subprocess.call("lsmod | grep -q g_mass_storage", shell=True) == 0


def is_hidden_file(name):
    return name.startswith(".") or name in HIDDEN_NAMES


@app.route("/")
def index():
    usb = is_usb_mode()
    mode = "USB (CNC)" if usb else "SIEĆ (UPLOAD)"
    files = []
    message = request.args.get("msg")
    if not UPLOAD_DIR and not message:
        message = "Brak konfiguracji CNC_UPLOAD_DIR"
    if not usb and UPLOAD_DIR and os.path.isdir(UPLOAD_DIR):
        files = [name for name in os.listdir(UPLOAD_DIR) if not is_hidden_file(name)]
    return render_template_string(HTML, mode=mode, files=files, message=message)

@app.route("/net", methods=["POST"])
def net():
    subprocess.call([NET_MODE_SCRIPT])
    return redirect(url_for("index"))

@app.route("/usb", methods=["POST"])
def usb():
    subprocess.call([USB_MODE_SCRIPT])
    return redirect(url_for("index"))

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
    return redirect(url_for("index"))

@app.route("/poweroff", methods=["POST"])
def poweroff():
    subprocess.call(["sudo", "poweroff"])
    return redirect(url_for("index"))

@app.route("/git-pull", methods=["POST"])
def git_pull():
    subprocess.call(["git", "pull", "--rebase"], cwd=CONTROL_REPO_DIR)
    return redirect(url_for("index"))

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
            return redirect(url_for("index", msg="Brak logu w systemd"))

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
        return redirect(url_for("index", msg="Błąd pobierania logu"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
