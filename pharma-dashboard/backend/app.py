import os, json, io, re, secrets
from datetime import timedelta
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from flask_session import Session
from authlib.integrations.flask_client import OAuth
import pyotp, qrcode, base64
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import pdfplumber

app = Flask(__name__, static_folder="../frontend/dist", static_url_path="/")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_sessions"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
Session(app)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

# --- Google OAuth ---
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# --- Authorized users store (file-based for f1-micro) ---
USERS_FILE = "/data/users.json"
DATA_FILE  = "/data/pharma_data.json"
os.makedirs("/data", exist_ok=True)

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"uploads": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

# --- Auth helpers ---
def get_current_user():
    return session.get("user")

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# --- OAuth routes ---
@app.route("/auth/login")
def login():
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    userinfo = token.get("userinfo")
    if not userinfo:
        return redirect("/#/auth?error=no_userinfo")
    email = userinfo["email"]
    users = load_users()
    if email not in users:
        # First time: create TOTP secret
        totp_secret = pyotp.random_base32()
        users[email] = {"totp_secret": totp_secret, "name": userinfo.get("name",""), "picture": userinfo.get("picture","")}
        save_users(users)
    session["pending_user"] = {"email": email, "name": users[email]["name"], "picture": users[email]["picture"]}
    session["authenticated"] = False
    return redirect("/#/2fa")

@app.route("/auth/2fa/qr")
def get_qr():
    pending = session.get("pending_user")
    if not pending:
        return jsonify({"error": "no pending session"}), 401
    users = load_users()
    email = pending["email"]
    secret = users[email]["totp_secret"]
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=email, issuer_name="PharmaDashboard")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return jsonify({"qr": f"data:image/png;base64,{b64}", "secret": secret})

@app.route("/auth/2fa/verify", methods=["POST"])
def verify_2fa():
    pending = session.get("pending_user")
    if not pending:
        return jsonify({"error": "no pending session"}), 401
    code = request.json.get("code","")
    users = load_users()
    email = pending["email"]
    totp = pyotp.TOTP(users[email]["totp_secret"])
    if totp.verify(code, valid_window=1):
        session["authenticated"] = True
        session["user"] = pending
        return jsonify({"ok": True, "user": pending})
    return jsonify({"error": "invalid code"}), 400

@app.route("/auth/me")
def me():
    if session.get("authenticated"):
        return jsonify({"user": session.get("user")})
    return jsonify({"user": None})

@app.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

# --- Data routes ---
@app.route("/api/data")
@require_auth
def get_data():
    return jsonify(load_data())

@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if not f.filename.endswith(".pdf"):
        return jsonify({"error": "only PDF"}), 400
    label = request.form.get("label", f.filename)
    rows = parse_pdf(f)
    data = load_data()
    data["uploads"].append({"label": label, "rows": rows})
    save_data(data)
    return jsonify({"ok": True, "rows": len(rows), "label": label})

@app.route("/api/upload/<int:idx>", methods=["DELETE"])
@require_auth
def delete_upload(idx):
    data = load_data()
    if 0 <= idx < len(data["uploads"]):
        data["uploads"].pop(idx)
        save_data(data)
        return jsonify({"ok": True})
    return jsonify({"error": "not found"}), 404

# --- PDF Parser ---
def parse_pdf(file_obj):
    rows = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.split("\n")
            for line in lines:
                parts = line.split()
                if len(parts) < 3:
                    continue
                # Try to extract numeric data
                nums = []
                for p in parts:
                    try:
                        nums.append(float(p.replace(",",".")))
                    except:
                        pass
                if nums:
                    rows.append({"raw": line, "values": nums})
    return rows

# --- Serve React SPA ---
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")

# --- Cloud Run Subpath Mounting ---
from werkzeug.middleware.dispatcher import DispatcherMiddleware

dummy_app = Flask('dummy')
@dummy_app.route('/')
def not_found():
    return "Not Found", 404

application = DispatcherMiddleware(dummy_app, {
    '/pizeta/dashboard': app
})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
