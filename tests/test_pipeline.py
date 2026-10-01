"""Regresiones sin acceso a Google ni descargas de modelos OCR."""

import io
from pathlib import Path
import runpy
import sys
import unittest
from unittest.mock import MagicMock, patch

import pymupdf

from extractor import extraer_documento
from parser import crear_clave_factura, parsear_factura
from validator import validar_factura


class AppPipelineTests(unittest.TestCase):
    def setUp(self):
        # Se sustituyen servicios externos para no escribir facturas reales.
        self.google = MagicMock()
        streamlit = MagicMock()
        streamlit.fragment.return_value = lambda function: MagicMock()
        with patch.dict(sys.modules, {
            "google_services": self.google,
            "streamlit": streamlit,
        }):
            app = runpy.run_path(str(Path(__file__).parents[1] / "app.py"))
        self.process = app["procesar_archivo"]
        self.cycle = app["ejecutar_ciclo"]
        self.document = {
            "texto": "Factura de prueba", "metodo": "PADDLEOCR",
            "lineas": [{"texto": "Servicio de prueba", "zona": "DETALLE"}],
            "tokens": [{"texto": "Servicio", "conf": 0.95}],
        }
        self.info = {"id": "test-id", "name": "test.pdf", "mimeType": "application/pdf"}
        self.google.descargar_archivo.return_value = io.BytesIO(b"test-pdf")
        self.google.factura_ya_registrada.return_value = False

    def run_process(self, state, errors=None):
        parse = MagicMock(return_value={"total": 121.0})
        with patch.dict(self.process.__globals__, {
            "extraer_documento": MagicMock(return_value=self.document),
            "parsear_factura": parse,
            "validar_factura": MagicMock(return_value=(state, errors or [])),
        }):
            result = self.process(self.info)
        parse.assert_called_once_with(self.document)
        self.assertEqual(result["metodo"], "PADDLEOCR")
        return result

    def test_ok_preserves_document_and_moves_to_processed(self):
        self.assertEqual(self.run_process("OK")["estado"], "OK")
        self.google.mover_a_procesadas.assert_called_once_with("test-id")
        self.google.mover_a_revisar.assert_not_called()
        saved = self.google.guardar_factura.call_args.args[0]
        self.assertEqual(saved["estado"], "OK")
        self.assertEqual(len(saved["hash"]), 64)

    def test_inferred_invoice_moves_to_processed(self):
        self.run_process("OK_INFERIDO")
        self.google.mover_a_procesadas.assert_called_once_with("test-id")
        self.google.mover_a_revisar.assert_not_called()
        self.assertEqual(self.google.guardar_factura.call_args.args[0]["estado"], "OK_INFERIDO")

    def test_invalid_invoice_is_saved_and_moved_to_review(self):
        self.run_process("REVISAR", ["Dato faltante"])
        self.google.mover_a_revisar.assert_called_once_with("test-id")
        self.google.mover_a_procesadas.assert_not_called()
        self.assertEqual(self.google.guardar_factura.call_args.args[0]["observaciones"], "Dato faltante")

    def test_duplicate_does_not_append_a_sheet_row(self):
        self.google.factura_ya_registrada.return_value = True
        self.assertEqual(self.run_process("OK")["estado"], "DUPLICADO")
        self.google.guardar_factura.assert_not_called()
        self.google.mover_a_procesadas.assert_called_once_with("test-id")

    def test_failed_invoice_does_not_stop_the_cycle(self):
        second = {**self.info, "id": "second"}
        self.google.listar_facturas_entrada.return_value = [self.info, second]
        with patch.dict(self.cycle.__globals__, {
            "procesar_archivo": MagicMock(side_effect=[ValueError("test error"), {"estado": "OK"}]),
        }):
            _, results = self.cycle()
        self.assertEqual([item["estado"] for item in results], ["ERROR", "OK"])
        self.google.mover_a_revisar.assert_called_once_with("test-id")


class ExtractionValidationTests(unittest.TestCase):
    def test_digital_pdf_pipeline_without_ocr(self):
        # CUIT generado para la prueba; no pertenece al maestro de proveedores.
        base = "2012345678"
        digit = 11 - sum(int(n) * p for n, p in zip(base, [5, 4, 3, 2, 7, 6, 5, 4, 3, 2])) % 11
        cuit = base + str(0 if digit == 11 else 9 if digit == 10 else digit)
        text = (
            "FACTURA A\nFecha: 01/10/2026\n"
            "Punto de Venta: 00001 Comp. Nro: 00000001\n"
            f"CUIT: {cuit}\nServicio de prueba\n"
            "Importe Neto Gravado: 100,00\nIVA: 21,00\n"
            "Importe Otros Tributos: 0,00\nImporte Total: 121,00\n"
        )
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((50, 50), text)
            data = pdf.tobytes()
        with patch("extractor._get_paddle", side_effect=AssertionError("OCR innecesario")):
            document = extraer_documento(io.BytesIO(data), "application/pdf", "test.pdf")
        self.assertEqual(document["metodo"], "PDF_TEXTO")
        invoice = parsear_factura(document)
        self.assertEqual(invoice["total"], 121.0)
        self.assertEqual(invoice["neto"], 100.0)
        self.assertEqual(invoice["iva"], 21.0)
        self.assertEqual(crear_clave_factura(invoice), f"{cuit}-A-00001-00000001")
        self.assertEqual(validar_factura(invoice), ("OK_INFERIDO", []))

    def test_missing_data_requires_review(self):
        state, errors = validar_factura(parsear_factura(""))
        self.assertEqual(state, "REVISAR")
        self.assertTrue(errors)

    def test_inconsistent_total_requires_review(self):
        invoice = {"neto": 100.0, "iva": 21.0, "total": 999.0}
        state, errors = validar_factura(invoice)
        self.assertEqual(state, "REVISAR")
        self.assertTrue(any("Total inconsistente" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
