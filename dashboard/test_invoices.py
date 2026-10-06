import json
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from werkzeug.security import generate_password_hash

from dashboard.app import create_app
from dashboard.invoices import (
    SHEET_FIELDS,
    InvoiceError,
    amount,
    invoice_date,
    period_records,
    public_record,
    reference,
    revision,
    summarize,
    validate_invoice,
)
from dashboard.sheets import SheetsStore, _column


def sample(**changes):
    return {"fecha_factura": "2026-09-22", "tipo": "C", "punto_venta": "2", "numero": "209",
            "proveedor": "Proveedor de prueba", "cuit_proveedor": "20246571156", "cliente": "KARPA SA",
            "cuit_cliente": "30561286686", "detalle": "Servicio", "neto": "730460,45", "iva": "0,00",
            "importe_otros_tributos": "0,00", "total": "730460,45", "cae": "86384210241427",
            "vencimiento_cae": "2026-10-02", "observaciones": "", "archivo": "Prueba", "estado": "", **changes}


class FakeSheet:
    def __init__(self, rows=None):
        self.headers = list(SHEET_FIELDS)
        self.rows = list(rows or [])
        self.calls = []

    def get_all_values(self):
        return [self.headers, *[[row.get(key, "") for key in self.headers] for row in self.rows]]

    def append_row(self, cells, **kwargs):
        self.calls.append(("append", kwargs))
        self.rows.append(dict(zip(self.headers, cells)))

    def update(self, values, range_name, **kwargs):
        self.calls.append(("update", kwargs))
        number = int(re.search(r"A(\d+):", range_name)[1])
        self.rows[number - 2] = dict(zip(self.headers, values[0]))


class InvoiceDomainTests(unittest.TestCase):
    def test_amounts_preserve_decimal_cents_and_argentine_grouping(self):
        for value in ("730460,45", "730.460,45", "730460.45", 730460.45, Decimal("730460.45")):
            self.assertEqual(amount(value), Decimal("730460.45"))
        self.assertEqual(amount("$ 1.234.567,89"), Decimal("1234567.89"))
        self.assertEqual(amount("1.234"), Decimal("1234.00"))
        self.assertEqual(amount("1.234.567"), Decimal("1234567.00"))
        self.assertEqual(amount("-1,25"), Decimal("-1.25"))
        self.assertIsNone(amount(None))
        self.assertIsNone(amount(""))
        for bad in (True, "text", "NaN", "1,2,3", "1.2345", "100000000000", .003):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                amount(bad)

    def test_periods_use_emission_date_and_can_select_month_year_independently(self):
        rows = [{"fecha_factura": date} for date in ("22/09/2026", "01/10/2026", "2025-09-01", "", "bad")]
        self.assertEqual(len(period_records(rows, "9", "2026")), 1)
        self.assertEqual(len(period_records(rows, "9")), 2)
        self.assertEqual(len(period_records(rows, year="2026")), 2)
        self.assertIs(period_records(rows), rows)
        self.assertEqual(period_records(rows, "12", "2024"), [])
        for month, year in (("0", ""), ("13", ""), ("a", ""), ("", "1800"), ("", "a")):
            with self.assertRaises(InvoiceError):
                period_records(rows, month, year)
        self.assertIsNone(invoice_date("31/02/2026"))

    def test_summary_sums_all_rows_without_float_rounding_or_missing_value_invention(self):
        rows = [{"total": "0,10", "neto": "0,10", "fecha_factura": "22/09/2026", "estado": "OK"} for _ in range(30)]
        rows += [{"total": "bad", "neto": "", "estado": "REVISAR"}, {"total": "", "estado": "REVISAR"}]
        result = summarize(rows)
        self.assertEqual(result["amounts"]["total"], "3.00")
        self.assertEqual(result["count"], 32)
        self.assertEqual(result["missing_total"], 2)
        self.assertEqual(result["missing_date"], 2)
        self.assertEqual(result["counts"], {"OK": 30, "REVISAR": 2})
        self.assertEqual(summarize([])["amounts"]["total"], "0.00")

    def test_normalization_and_complete_manual_invoice(self):
        row, warnings = validate_invoice(sample(cuit_proveedor="20-24657115-6"))
        self.assertEqual(warnings, [])
        self.assertEqual(row["estado"], "OK")
        self.assertEqual(row["punto_venta"], "00002")
        self.assertEqual(row["numero"], "00000209")
        self.assertEqual(row["fecha_factura"], "22/09/2026")
        self.assertEqual(row["total"], 730460.45)
        self.assertEqual(row["clave_factura"], "20246571156-C-00002-00000209")

    def test_incomplete_and_contradictory_data_are_explicitly_for_review(self):
        row, warnings = validate_invoice(sample(tipo="", cuit_proveedor="", neto="", iva=""))
        self.assertEqual(row["estado"], "REVISAR")
        self.assertTrue(warnings)
        self.assertEqual(row["clave_factura"], "")
        row, warnings = validate_invoice(sample(total="730461,45"))
        self.assertEqual(row["estado"], "REVISAR")
        self.assertIn("no coincide", warnings[0])
        self.assertEqual(validate_invoice(sample(estado="REVISAR"))[0]["estado"], "REVISAR")
        self.assertEqual(validate_invoice(sample(cuit_proveedor="20246571150"))[0]["estado"], "REVISAR")
        self.assertEqual(validate_invoice(sample(neto="0", total="0"))[0]["total"], 0)

    def test_validation_errors_are_attached_to_fields(self):
        cases = {"proveedor": "", "fecha_factura": "bad", "total": "bad", "tipo": "Z",
                 "punto_venta": "123456", "numero": "x", "cuit_cliente": "123", "cae": "123",
                 "vencimiento_cae": "bad", "estado": "ERROR", "detalle": "x" * 5001,
                 "cliente": [], "neto": "-1", "iva": .003}
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(InvoiceError) as error:
                validate_invoice(sample(**{key: value}))
            self.assertIn(key, error.exception.fields)
        for payload in (None, [], {"drive_id": "overwrite"}):
            with self.assertRaises(InvoiceError):
                validate_invoice(payload)

    def test_revision_compares_numeric_formats_and_references_keep_private_identity_hidden(self):
        original = {"hash": "private", "drive_id": "abc", "total": "730460,45"}
        self.assertEqual(revision(original), revision({**original, "total": 730460.45}))
        self.assertNotEqual(revision(original), revision({**original, "total": "730461,45"}))
        self.assertEqual(reference(original), reference({**original, "numero": "different"}))
        public = public_record(original)
        self.assertNotIn("hash", public)
        self.assertNotIn("clave_factura", public)
        self.assertEqual(len(public["_ref"]), 64)
        self.assertNotEqual(reference({}, 0), reference({}, 1))
        self.assertEqual(len(revision({"total": "bad"})), 64)


class SheetsStoreTests(unittest.TestCase):
    def setUp(self):
        self.sheet = FakeSheet()
        self.store = SheetsStore(self.sheet)
        self.payload = {"invoice": sample(), "request_key": str(uuid4())}

    def test_create_is_idempotent_and_uses_raw_to_preserve_text_and_leading_zeros(self):
        self.payload["invoice"]["detalle"] = '=IMPORTXML("https://example.invalid")'
        first = self.store.save(self.payload)
        second = self.store.save(self.payload)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(self.sheet.rows), 1)
        self.assertEqual(self.sheet.calls, [("append", {"value_input_option": "RAW"})])
        self.assertEqual(self.sheet.rows[0]["punto_venta"], "00002")
        self.assertTrue(self.sheet.rows[0]["detalle"].startswith("="))

    def test_existing_invoice_is_updated_and_private_source_fields_are_preserved(self):
        self.store.save(self.payload)
        row = self.sheet.rows[0]
        row.update(drive_id="test-drive", hash="private-hash", fecha_carga="01/10/2026 12:00:00")
        ref = reference(row)
        editing = self.store.get(ref)
        result = self.store.save({"invoice": sample(detalle="Corregida"), "revision": editing["_revision"]}, ref)
        self.assertFalse(result["created"])
        self.assertEqual(len(self.sheet.rows), 1)
        self.assertEqual(self.sheet.rows[0]["detalle"], "Corregida")
        self.assertEqual(self.sheet.rows[0]["drive_id"], "test-drive")
        self.assertEqual(self.sheet.rows[0]["hash"], "private-hash")
        self.assertEqual(self.sheet.rows[0]["fecha_carga"], "01/10/2026 12:00:00")
        self.assertEqual(self.sheet.calls[-1], ("update", {"value_input_option": "RAW"}))

    def test_stale_editor_cannot_overwrite_newer_change(self):
        result = self.store.save(self.payload)
        editing = result["invoice"]
        self.sheet.rows[0]["detalle"] = "Cambio desde Sheets"
        with self.assertRaises(InvoiceError) as error:
            self.store.save({"invoice": sample(), "revision": editing["_revision"]}, editing["_ref"])
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.sheet.rows[0]["detalle"], "Cambio desde Sheets")

    def test_duplicate_fiscal_key_and_invalid_request_keys_are_rejected(self):
        self.store.save(self.payload)
        with self.assertRaises(InvoiceError) as error:
            self.store.save({**self.payload, "request_key": str(uuid4())})
        self.assertEqual(error.exception.status, 409)
        for payload in (None, {"unexpected": 1}, {"invoice": sample(), "request_key": "bad"}):
            with self.assertRaises(InvoiceError):
                self.store.save(payload)

    def test_missing_ambiguous_records_and_changed_layout_do_not_update_any_row(self):
        with self.assertRaises(InvoiceError) as error:
            self.store.get("a" * 64)
        self.assertEqual(error.exception.status, 404)
        result = self.store.save(self.payload)
        self.sheet.rows.append(dict(self.sheet.rows[0]))
        with self.assertRaises(InvoiceError) as error:
            self.store.get(result["invoice"]["_ref"])
        self.assertEqual(error.exception.status, 409)
        with self.assertRaises(InvoiceError):
            self.store.save({"invoice": sample(), "revision": "bad"}, "a" * 64)
        self.sheet.headers = ["bad"]
        with self.assertRaises(InvoiceError) as error:
            self.store.get("a" * 64)
        self.assertEqual(error.exception.status, 503)

    def test_recent_changes_are_visible_until_worker_snapshot_matches(self):
        result = self.store.save(self.payload)
        saved = dict(self.sheet.rows[0])
        self.assertEqual(len(self.store.view([])), 1)
        stale = {**saved, "total": "old"}
        self.assertEqual(self.store.view([stale])[0]["total"], 730460.45)
        extra = {"hash": "new-automatic", "archivo": "Automática"}
        self.assertEqual(len(self.store.view([saved, extra])), 2)
        self.assertFalse(self.store.pending)
        self.assertEqual(self.store.get(result["invoice"]["_ref"])["total"], 730460.45)

    def test_missing_reference_name_is_generated_and_extra_columns_are_kept(self):
        self.sheet.headers.append("extra")
        self.store.save({**self.payload, "invoice": sample(archivo="")})
        self.assertTrue(self.sheet.rows[0]["archivo"].startswith("Factura C"))
        self.sheet.rows[0]["extra"] = "keep"
        row = self.sheet.rows[0]
        self.store.save({"invoice": sample(), "revision": revision(row)}, reference(row))
        self.assertEqual(self.sheet.rows[0]["extra"], "keep")
        self.assertEqual(_column(22), "V")
        self.assertEqual(_column(27), "AA")

    def test_google_initialization_is_lazy_and_uses_only_sheets_scope(self):
        client = MagicMock()
        store = SheetsStore()
        with patch.dict("os.environ", {"DASHBOARD_GOOGLE_FILE": "secret", "SPREADSHEET_ID": "sheet",
                                      "WORKSHEET_NAME": "Facturas"}), \
                patch("google.oauth2.service_account.Credentials.from_service_account_file") as credentials, \
                patch("gspread.authorize", return_value=client):
            store._connect()
            store._connect()
        credentials.assert_called_once_with("secret", scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client.set_timeout.assert_called_once_with(15)


class InvoiceApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sheet = FakeSheet()
        self.store = SheetsStore(self.sheet)
        auth = {"username": "test", "password_hash": generate_password_hash("test", method="pbkdf2:sha256:1000"),
                "session_secret": "test-secret"}
        self.app = create_app(auth, self.root, secure=False, store=self.store)
        self.app.testing = True
        self.client = self.app.test_client()
        response = self.client.get("/login")
        csrf = re.search('name="csrf" value="([^"]+)"', response.text)[1]
        self.client.post("/login", data={"username": "test", "password": "test", "csrf": csrf})
        with self.client.session_transaction() as session:
            self.headers = {"X-CSRF-Token": session["csrf"]}

    def test_create_edit_and_read_require_login_and_csrf(self):
        public = self.app.test_client()
        for method, path in (("post", "/api/invoices"), ("get", "/api/invoices/" + "a" * 64),
                             ("put", "/api/invoices/" + "a" * 64)):
            self.assertEqual(getattr(public, method)(path).status_code, 401)
        payload = {"invoice": sample(), "request_key": str(uuid4())}
        self.assertEqual(self.client.post("/api/invoices", json=payload).status_code, 400)
        created = self.client.post("/api/invoices", json=payload, headers=self.headers)
        self.assertEqual(created.status_code, 201)
        row = created.json["invoice"]
        path = "/api/invoices/" + row["_ref"]
        self.assertEqual(self.client.get(path).status_code, 200)
        updated = self.client.put(path, json={"invoice": sample(detalle="Editada"), "revision": row["_revision"]}, headers=self.headers)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["invoice"]["detalle"], "Editada")
        self.assertEqual(len(self.sheet.rows), 1)

    def test_invalid_input_and_google_failures_do_not_expose_private_errors(self):
        self.assertEqual(self.client.get("/api/invoices/bad").status_code, 404)
        self.assertEqual(self.client.post("/api/invoices", data="bad", headers=self.headers).status_code, 415)
        response = self.client.post("/api/invoices", json={"invoice": {}}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertIn("total", response.json["fields"])
        self.store.sheet.get_all_values = MagicMock(side_effect=RuntimeError("private-token"))
        response = self.client.get("/api/invoices/" + "a" * 64)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-token", response.text)

    def test_summary_uses_all_period_rows_even_when_table_is_paginated_or_searched(self):
        rows = [{"fecha_factura": "22/09/2026", "total": "0,10", "archivo": str(i)} for i in range(30)]
        rows += [{"fecha_factura": "01/10/2026", "total": "730460,45", "archivo": "Octubre"}]
        (self.root / "invoices.json").write_text(json.dumps({"records": rows}), encoding="utf-8")
        result = self.client.get("/api/invoices?month=9&year=2026&q=29").json
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["summary"]["count"], 30)
        self.assertEqual(result["summary"]["amounts"]["total"], "3.00")
        self.assertEqual(result["years"], [2026])
        self.assertEqual(self.client.get("/api/invoices?month=13").status_code, 400)


if __name__ == "__main__":
    unittest.main()
