import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from dashboard.app import LoginLimiter, Snapshots, age_seconds, create_app


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.auth = {"username": "test", "password_hash": generate_password_hash("correct", method="pbkdf2:sha256:1000"),
                     "session_secret": "test-session-secret"}
        self.app = create_app(self.auth, self.root)
        self.app.testing = True
        self.client = self.app.test_client()

    def write(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")

    def login(self, username="test", password="correct"):
        response = self.client.get("/login")
        csrf = re.search('name="csrf" value="([^"]+)"', response.text).group(1)
        return self.client.post("/login", data={"username": username, "password": password, "csrf": csrf})

    def test_all_data_routes_require_authentication(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        for path in ("/api/status", "/api/invoices"):
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get("/healthz").json, {"status": "ok"})

    def test_login_logout_csrf_and_cookie_security(self):
        self.assertEqual(self.client.post("/login", data={}).status_code, 400)
        self.assertEqual(self.login(password="wrong").status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/login").status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/logout", data={}).status_code, 400)
        with self.client.session_transaction() as session:
            csrf = session["csrf"]
        self.assertEqual(self.client.post("/logout", data={"csrf": csrf}).status_code, 302)
        self.assertEqual(self.client.get("/api/status").status_code, 401)

    def test_login_throttles_repeated_failures(self):
        for _ in range(8):
            self.assertEqual(self.login(password="wrong").status_code, 401)
        self.assertEqual(self.login(password="wrong").status_code, 429)

    def test_history_filter_pagination_search_and_no_secret_fields(self):
        self.login()
        records = [{"archivo": f"archivo-{i}.pdf", "estado": "OK" if i % 2 else "REVISAR",
                    "proveedor": "Árbol SA", "neto": 100, "hash": "not-for-browser"} for i in range(60)]
        self.write("invoices.json", {"records": records, "synced_at": datetime.now(timezone.utc).isoformat()})
        response = self.client.get("/api/invoices?size=25&page=2").json
        self.assertEqual(len(response["records"]), 25)
        self.assertEqual(response["records"][0]["archivo"], "archivo-34.pdf")
        self.assertEqual(response["all_total"], 60)
        self.assertEqual(response["counts"], {"OK": 30, "REVISAR": 30})
        self.assertNotIn("hash", response["records"][0])
        self.assertEqual(self.client.get("/api/invoices?state=OK").json["total"], 30)
        self.assertEqual(self.client.get("/api/invoices?q=archivo-59").json["total"], 1)
        self.assertEqual(self.client.get("/api/invoices?q=ÁRBOL").json["total"], 60)
        self.assertEqual(self.client.get("/api/invoices?q=nomatch").json["total"], 0)
        for query in ("size=7", "page=abc", "size=abc"):
            self.assertEqual(self.client.get("/api/invoices?" + query).status_code, 400)

    def test_health_offline_warning_and_processing_without_percent_invention(self):
        self.login()
        self.assertTrue(self.client.get("/api/status").json["stale"])
        recent = datetime.now(timezone.utc).isoformat()
        base = {"heartbeat_at": recent, "status": "processing", "current": {"archivo": "a.pdf", "stage": "OCR"}}
        self.write("state.json", base)
        self.assertEqual(self.client.get("/api/status").json["health"], "healthy")
        for changes in ({"last_cycle_error": "TimeoutError"}, {"history_error": "Error"},
                        {"metrics_error": "Error"}, {"metrics": {"memory_total": 100, "memory_available": 5}},
                        {"metrics": {"disk_total": 100, "disk_available": 5}}, {"counts": {"ERROR": 1}}):
            self.write("state.json", {**base, **changes})
            self.assertEqual(self.client.get("/api/status").json["health"], "warning")
        old = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
        self.write("state.json", {**base, "heartbeat_at": old})
        self.assertEqual(self.client.get("/api/status").json["health"], "offline")
        self.write("state.json", {**base, "status": "stopped"})
        self.assertEqual(self.client.get("/api/status").json["health"], "offline")

    def test_security_headers_and_payload_limit(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.post("/login", data={"password": "x" * 9000}).status_code, 413)

    def test_snapshot_atomic_replacement_cache_and_invalid_files(self):
        reader = Snapshots(self.root)
        self.assertEqual(reader.read("missing"), {})
        self.write("invoices.json", {"records": [{"estado": "OK"}]})
        first = reader.read("invoices.json")
        self.assertIs(first, reader.read("invoices.json"))
        self.write("next.json", {"records": [{"estado": "REVISAR"}]})
        (self.root / "next.json").replace(self.root / "invoices.json")
        self.assertEqual(reader.read("invoices.json")["records"][0]["estado"], "REVISAR")
        self.write("invalid", [])
        self.assertEqual(reader.read("invalid"), {})
        (self.root / "bad").write_text("{", encoding="utf-8")
        self.assertEqual(reader.read("bad"), {})
        with patch.object(Path, "stat") as stat:
            stat.return_value.st_size = 51 * 1024 * 1024
            self.assertEqual(reader.read("large"), {})

    def test_config_must_be_complete_and_timestamps_are_checked(self):
        with self.assertRaises(ValueError):
            create_app({"username": "test"}, self.root)
        self.assertIsNone(age_seconds("bad"))
        self.assertIsNone(age_seconds(None))

    def test_limiter_expires_old_attempts_and_bounds_addresses(self):
        limiter = LoginLimiter()
        with patch("dashboard.app.time.monotonic", return_value=0):
            for _ in range(8):
                self.assertTrue(limiter.allow("test"))
            self.assertFalse(limiter.allow("test"))
        with patch("dashboard.app.time.monotonic", return_value=301):
            self.assertTrue(limiter.allow("test"))
            for i in range(1100):
                limiter.allow(str(i))
        self.assertEqual(len(limiter.attempts), 1024)


if __name__ == "__main__":
    unittest.main()
