import json
import os, io, secrets
from datetime import timedelta
from pathlib import Path
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from flask_session import Session
from authlib.integrations.flask_client import OAuth
import pyotp, qrcode, base64
from werkzeug.middleware.proxy_fix import ProxyFix

import db_store
from datamart_summary import build_dashboard_api_payload, list_datamart_years

_BACKEND_DIR = Path(__file__).resolve().parent
# Dev: app/backend/app.py → ../frontend/dist. Docker: /app/app.py → ./frontend/dist
_cand = _BACKEND_DIR / "frontend" / "dist"
_FRONTEND_DIST = _cand if _cand.is_dir() else (_BACKEND_DIR.parent / "frontend" / "dist")
app = Flask(__name__, static_folder=str(_FRONTEND_DIST), static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_sessions"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
# Local http://localhost: SESSION_COOKIE_SECURE=False; Cloud Run sets K_SERVICE → default True
def _session_cookie_secure() -> bool:
    if (v := os.environ.get("SESSION_COOKIE_SECURE")) is not None:
        return str(v).lower() in ("1", "true", "yes")
    return bool(os.environ.get("K_SERVICE"))


app.config["SESSION_COOKIE_SECURE"] = _session_cookie_secure()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
Session(app)

_AUTH_DEV = os.environ.get("AUTH_MODE", "").lower() == "development"
_DEFAULT_ALLOWED_EMAILS = "bertnic@gmail.com,sedrananna@gmail.com"
_ALLOWED_GOOGLE_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("ALLOWED_GOOGLE_EMAILS", _DEFAULT_ALLOWED_EMAILS).split(",")
    if e.strip()
)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_proto=1)

# --- Google OAuth ---
_oauth_id = os.environ.get("GOOGLE_CLIENT_ID")
_oauth_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
if _AUTH_DEV and (not _oauth_id or not _oauth_secret):
    _oauth_id = _oauth_id or "dev-local.apps.googleusercontent.com"
    _oauth_secret = _oauth_secret or "dev-local-not-used"
elif not _oauth_id or not _oauth_secret:
    raise RuntimeError(
        "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or AUTH_MODE=development for local UI testing."
    )

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=_oauth_id,
    client_secret=_oauth_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

if _AUTH_DEV:
    @app.before_request
    def _development_auth_session() -> None:
        session.permanent = True
        session["authenticated"] = True
        session.setdefault(
            "user",
            {"email": "dev@local.test", "name": "Local Dev", "picture": ""},
        )

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
        return redirect(url_for("serve", path="") + "#/auth?error=no_userinfo")
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return redirect(url_for("serve", path="") + "#/auth?error=no_email")
    if not _AUTH_DEV and email not in _ALLOWED_GOOGLE_EMAILS:
        session.clear()
        return redirect(url_for("serve", path="") + "#/auth?error=unauthorized_email")
    users = db_store.users_as_dict()
    display_name = userinfo.get("name", "") or ""
    picture_url = userinfo.get("picture", "") or ""
    if email not in users:
        totp_secret = pyotp.random_base32()
        db_store.insert_user(
            email,
            totp_secret,
            display_name,
            picture_url,
        )
    else:
        db_store.update_user_profile(email, display_name, picture_url)
    users = db_store.users_as_dict()
    session["pending_user"] = {"email": email, "name": users[email]["name"], "picture": users[email]["picture"]}
    session["authenticated"] = False
    return redirect(url_for("serve", path="") + "#/2fa")

@app.route("/auth/2fa/qr")
def get_qr():
    pending = session.get("pending_user")
    if not pending:
        return jsonify({"error": "no pending session"}), 401
    users = db_store.users_as_dict()
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
    users = db_store.users_as_dict()
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

def _datamart_summary_params():
    """Return ``(year, product_filter)`` from GET query or POST JSON body."""
    if request.method == "POST" and request.is_json:
        body = request.get_json(silent=True) or {}
        raw_y = body.get("year")
        if raw_y is not None and raw_y != "":
            try:
                y = int(raw_y)
            except (TypeError, ValueError):
                y = None
        else:
            y = None
        rp = body.get("products")
        if not isinstance(rp, list):
            rp = []
        raw_products = [x for x in rp if isinstance(x, str)]
    else:
        y = request.args.get("year", type=int)
        raw_products = list(request.args.getlist("product"))
        if not raw_products:
            pj = request.args.get("products_json")
            if pj:
                try:
                    parsed = json.loads(pj)
                    if isinstance(parsed, list):
                        raw_products = [x for x in parsed if isinstance(x, str)]
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
    product_filter = frozenset(
        p.strip() for p in raw_products if isinstance(p, str) and p.strip()
    ) or None
    return y, product_filter


# --- Data routes ---
@app.route("/api/datamart/summary", methods=["GET", "POST"])
@require_auth
def datamart_summary():
    """IMS vendite da tabella ``sales`` (+ ``target``); ``?year=`` o JSON ``{year, products}``; YoY nel payload."""
    db_store.ensure_initialized()
    y, product_filter = _datamart_summary_params()
    conn = db_store.connect()
    try:
        payload = build_dashboard_api_payload(conn, y, product_filter=product_filter)
        if (
            _AUTH_DEV
            and request.args.get("debug") == "1"
            and payload is not None
        ):
            payload = {
                **payload,
                "_debug": {
                    "database": str(db_store.database_file_path()),
                    "years_in_db": list_datamart_years(conn),
                },
            }
        resp = jsonify(payload if payload is not None else None)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp
    finally:
        conn.close()

# --- Serve React SPA ---
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    # If the path points to an existing file in static_folder, serve it
    full_path = os.path.join(app.static_folder, path)
    if path and os.path.exists(full_path) and os.path.isfile(full_path):
        return send_from_directory(app.static_folder, path)
    # Otherwise, fallback to index.html for React Router
    return send_from_directory(app.static_folder, "index.html")

# --- Cloud Run Subpath Mounting ---
from werkzeug.middleware.dispatcher import DispatcherMiddleware

dummy_app = Flask('dummy')
@dummy_app.route('/')
def not_found():
    return "Pizeta — use /pizeta/dashboard/ to access the dashboard app.", 404

application = DispatcherMiddleware(dummy_app, {
    '/pizeta/dashboard': app
})

if __name__ == "__main__":
    # Serve the same WSGI stack as Cloud Run (``/pizeta/dashboard`` mount) so local URLs match
    # ``vite`` ``base`` and built static assets under ``/pizeta/dashboard/...``.
    from werkzeug.serving import run_simple

    port = int(os.environ.get("PORT", 8080))
    run_simple(
        "0.0.0.0",
        port,
        application,
        use_reloader=False,
        threaded=True,
    )
