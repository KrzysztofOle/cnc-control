from flask import Flask, request, redirect, url_for, render_template_string, send_file
import subprocess
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
USB_MOUNT = os.environ.get("CNC_USB_MOUNT", "/mnt/cnc_usb")
UPLOAD_DIR = USB_MOUNT
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
</style>
</head>

<body>
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

</body>
</html>
"""

def is_usb_mode():
    return subprocess.call("lsmod | grep -q g_mass_storage", shell=True) == 0

@app.route("/")
def index():
    usb = is_usb_mode()
    mode = "USB (CNC)" if usb else "SIEĆ (UPLOAD)"
    files = []
    if not usb and os.path.isdir(UPLOAD_DIR):
        files = os.listdir(UPLOAD_DIR)
    message = request.args.get("msg")
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
    if not os.path.isfile(WEBUI_LOG_PATH):
        return redirect(url_for("index", msg="Brak pliku logu"))
    try:
        return send_file(WEBUI_LOG_PATH, as_attachment=True)
    except Exception:
        return redirect(url_for("index", msg="Błąd pobierania logu"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
