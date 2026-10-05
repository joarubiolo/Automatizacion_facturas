"""Regresiones de lectura regional usando la conversión real de gspread."""

import runpy
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from gspread import Worksheet


class SheetRecordTests(unittest.TestCase):
    def setUp(self):
        # Usamos get_all_records real, pero sustituimos su lectura HTTP.
        self.sheet = object.__new__(Worksheet)
        self.sheet.get = MagicMock()
        client = MagicMock()
        client.open_by_key.return_value.worksheet.return_value = self.sheet
        with patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
                patch("googleapiclient.discovery.build"), \
                patch("gspread.authorize", return_value=client):
            self.services = runpy.run_path(str(Path(__file__).parents[1] / "google_services.py"))

    def records(self, **values):
        self.sheet.get.return_value = [list(values), list(values.values())]
        return self.services["obtener_registros"]()[0]

    def test_decimal_comma_is_not_removed_from_invoice_amounts(self):
        row = self.records(neto="730460,45", iva="0", importe_otros_tributos="0", total="730460,45")
        self.assertEqual(row["neto"], "730460,45")
        self.assertEqual(row["total"], "730460,45")
        self.assertEqual(row["iva"], "0")

    def test_grouped_amounts_dates_and_identifiers_keep_their_format(self):
        values = {"total": "730.460,45", "fecha_carga": "27/09/2026 20:34:10",
                  "punto_venta": "00002", "numero": "00000209", "cae": "86384210241427",
                  "cuit_proveedor": "20246571156", "iva": ""}
        self.assertEqual(self.records(**values), values)

    def test_dot_decimal_and_native_numbers_are_not_rescaled(self):
        values = {"neto": "730460.45", "total": 730460.45, "iva": 0}
        self.assertEqual(self.records(**values), values)

    def test_duplicate_detection_still_matches_each_existing_identity(self):
        self.sheet.get.return_value = [
            ["drive_id", "hash", "clave_factura"],
            ["test-drive", "test-hash", "20246571156-C-00002-00000209"],
        ]
        duplicate = self.services["factura_ya_registrada"]
        self.assertTrue(duplicate("test-drive", "different", None))
        self.assertTrue(duplicate("different", "test-hash", None))
        self.assertTrue(duplicate("different", "different", "20246571156-C-00002-00000209"))
        self.assertFalse(duplicate("different", "different", "different"))


if __name__ == "__main__":
    unittest.main()
