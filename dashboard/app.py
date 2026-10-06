"""Panel privado: monitoreo, resumen y gestión de datos en Sheets, sin OCR."""

import json
import os
import secrets
import time
from collections import Counter, OrderedDict, deque
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from dashboard.invoices import (
    InvoiceError,
    invoice_date,
    period_records,
    public_record,
    summarize,
)
from dashboard.sheets import SheetsStore

FIELDS = (
    "fecha_carga", "estado", "fecha_factura", "tipo", "punto_venta", "numero",
    "proveedor", "cuit_proveedor", "cliente", "cuit_cliente", "detalle", "neto", "iva",
    "importe_otros_tributos", "total", "cae", "vencimiento_cae", "archivo", "drive_id", "observaciones",
)


class LoginLimiter:
    def __init__(self):
        self.attempts = OrderedDict()
        self.lock = Lock()

    def allow(self, address):
        with self.lock:
            now = time.monotonic()
            attempts = self.attempts.pop(address, deque())
            while attempts and attempts[0] < now - 300:
                attempts.popleft()
            self.attempts[address] = attempts
            if len(self.attempts) > 1024:
                self.attempts.popitem(last=False)
            if len(attempts) >= 8:
                return False
            attempts.append(now)
            return True


def age_seconds(timestamp):
    try:
        return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)).total_seconds())
    except (TypeError, ValueError):
        return None


class Snapshots:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.cache = {}
        self.lock = Lock()

    def read(self, name):
        with self.lock:
            path = self.directory / name
            try:
                info = path.stat()
                if info.st_size > 50 * 1024 * 1024:
                    return {}
                cached = self.cache.get(name)
                if cached and cached[0] == info.st_mtime_ns:
                    return cached[1]
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return {}
                self.cache[name] = info.st_mtime_ns, data
                return data
            except (OSError, ValueError):
                return {}


def create_app(auth=None, directory=None, secure=True, store=None):
    if auth is None:
        auth = json.loads(Path(os.environ["DASHBOARD_AUTH_FILE"]).read_text(encoding="utf-8"))
    if not all(auth.get(key) for key in ("username", "password_hash", "session_secret")):
        raise ValueError("Falta la configuración privada de acceso al panel")
    app = Flask(__name__)
    app.config.update(SECRET_KEY=auth["session_secret"], SESSION_COOKIE_SECURE=secure,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=28800, MAX_CONTENT_LENGTH=32768)
    # Solo el proxy interno tiene acceso al puerto de la API.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    snapshots = Snapshots(directory or os.getenv("MONITOR_DIR", "/monitor"))
    if store is None and os.getenv("DASHBOARD_GOOGLE_FILE"):
        store = SheetsStore()
    limiter = LoginLimiter()

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                                       "base-uri 'self'; form-action 'self'",
        })
        return response

    def protected(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("authenticated"):
                if request.path.startswith("/api/"):
                    return jsonify(error="Iniciá sesión para continuar"), 401
                return redirect(url_for("login"))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("authenticated"):
            return redirect(url_for("index"))
        error, code = None, 200
        session.setdefault("csrf", secrets.token_urlsafe(32))
        if request.method == "POST":
            if not secrets.compare_digest(request.form.get("csrf", ""), session["csrf"]):
                error, code = "La sesión venció. Recargá la página.", 400
            elif not limiter.allow(request.remote_addr):
                error, code = "Demasiados intentos. Esperá cinco minutos.", 429
            else:
                user_ok = secrets.compare_digest(request.form.get("username", "").encode(),
                                                 auth["username"].encode())
                password_ok = check_password_hash(auth["password_hash"], request.form.get("password", ""))
                if user_ok and password_ok:
                    session.clear()
                    session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
                    session.permanent = True
                    return redirect(url_for("index"))
                error, code = "Usuario o contraseña incorrectos.", 401
        return render_template("login.html", error=error, csrf=session["csrf"]), code

    @app.post("/logout")
    @protected
    def logout():
        if not secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            return jsonify(error="Solicitud inválida"), 400
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @protected
    def index():
        return render_template("index.html", csrf=session["csrf"], editing_enabled=store is not None)

    @app.get("/api/status")
    @protected
    def status():
        state = dict(snapshots.read("state.json"))
        age = age_seconds(state.get("heartbeat_at"))
        stale = age is None or age > 25
        if stale or state.get("status") == "stopped":
            health = "offline"
        elif state.get("last_cycle_error") or state.get("history_error") or state.get("metrics_error"):
            health = "warning"
        else:
            health = "healthy"
        metrics = state.get("metrics", {})
        memory_total = metrics.get("memory_total", 0)
        disk_total = metrics.get("disk_total", 0)
        if health == "healthy" and (
            memory_total and metrics.get("memory_available", 0) / memory_total < 0.1
            or disk_total and metrics.get("disk_available", 0) / disk_total < 0.1
            or state.get("counts", {}).get("ERROR", 0)
        ):
            health = "warning"
        state.update(health=health, stale=stale, heartbeat_age=age,
                     history_synced_at=snapshots.read("invoices.json").get("synced_at"))
        state.pop("events", None)
        return jsonify(state)

    @app.get("/api/invoices")
    @protected
    def invoices():
        try:
            page = max(1, min(100000, int(request.args.get("page", 1))))
            size = int(request.args.get("size", 25))
            if size not in (25, 50, 100):
                raise ValueError
        except ValueError:
            return jsonify(error="Paginación inválida"), 400
        data = snapshots.read("invoices.json")
        all_records = data.get("records", [])
        if store is not None:
            all_records = store.view(all_records)
        try:
            records = period_records(all_records, request.args.get("month", ""), request.args.get("year", ""))
        except InvoiceError as exc:
            return jsonify(error=str(exc)), exc.status
        counts = Counter(str(row.get("estado", "")) for row in records)
        state_filter = request.args.get("state", "")[:30]
        query = request.args.get("q", "")[:200].casefold().strip()
        filtered = []
        references = {id(row): index for index, row in enumerate(all_records)}
        for row in reversed(records):
            if state_filter and str(row.get("estado", "")) != state_filter:
                continue
            if query and query not in " ".join(str(row.get(key, "")) for key in
                                               ("archivo", "proveedor", "detalle", "numero", "cuit_proveedor")).casefold():
                continue
            filtered.append(public_record(row, references[id(row)]))
        start = (page - 1) * size
        years = sorted({date.year for row in all_records if (date := invoice_date(row.get("fecha_factura")))}, reverse=True)
        return jsonify(records=filtered[start:start + size], total=len(filtered), all_total=len(all_records),
                       page=page, size=size, counts=dict(counts), synced_at=data.get("synced_at"),
                       summary=summarize(records), years=years, editing_enabled=store is not None)

    @app.route("/api/invoices/<ref>", methods=["GET", "PUT"])
    @app.post("/api/invoices")
    @protected
    def edit_invoice(ref=None):
        if request.method != "GET" and not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session.get("csrf", "")):
            return jsonify(error="La sesión venció. Recargá el panel antes de guardar."), 400
        if store is None:
            return jsonify(error="La carga manual todavía no está disponible"), 503
        if ref is not None and (len(ref) != 64 or any(char not in "0123456789abcdef" for char in ref)):
            return jsonify(error="Factura no encontrada"), 404
        try:
            if request.method == "GET":
                return jsonify(invoice=store.get(ref))
            if not request.is_json:
                return jsonify(error="Enviá los campos de la factura como datos válidos"), 415
            result = store.save(request.get_json(silent=True), ref)
            return jsonify(result), 201 if result["created"] else 200
        except InvoiceError as exc:
            return jsonify(error=str(exc), fields=exc.fields), exc.status
        except Exception as exc:  # noqa: BLE001 - los detalles de Google pueden incluir credenciales
            app.logger.warning("Falló la gestión de factura (%s)", type(exc).__name__)
            return jsonify(error="No se pudo confirmar el guardado en Sheets. Tus datos siguen en el formulario; intentá nuevamente."), 503

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    return app
