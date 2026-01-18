from flask import Flask, request, redirect, url_for, render_template_string
import subprocess
import os

app = Flask(__name__)
UPLOAD_DIR = "/mnt/cnc_usb"

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
    return render_template_string(HTML, mode=mode, files=files)

@app.route("/net", methods=["POST"])
def net():
    subprocess.call(["/home/andrzej/net_mode.sh"])
    return redirect(url_for("index"))

@app.route("/usb", methods=["POST"])
def usb():
    subprocess.call(["/home/andrzej/usb_mode.sh"])
    return redirect(url_for("index"))

@app.route("/upload", methods=["POST"])
def upload():
    if not is_usb_mode():
        f = request.files["file"]
        f.save(os.path.join(UPLOAD_DIR, f.filename))
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
