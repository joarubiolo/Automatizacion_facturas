import unittest
from unittest.mock import patch

from PIL import Image

from extractor import _agrupar_lineas, _ocr_regiones
from inference_engine import inferir_importes, inferir_detalle, normalizar_importe
from parser import parsear_factura
from table_analysis import _total_in_words
from validator import validar_factura


def token(text, x, y, w=80, confidence=.95, reading=None):
    return {"texto": text, "x": x, "y": y, "w": w, "h": 15,
            "x_rel": x / 1000, "y_rel": y / 1000, "pagina": 1,
            "conf": confidence, "motor": "PADDLEOCR", "lectura": reading, "zona": "DETALLE"}


def document(tokens, alternatives=()):
    lines = _agrupar_lineas(tokens)
    return {"tokens": tokens, "lineas": lines, "texto": "\n".join(l["texto"] for l in lines),
            "ocr_alternativas": list(alternatives)}


def money_document(net="100,00", vat="21,00", other=None, total="121,00", alternatives=()):
    tokens = [token("SUBTOTAL", 80, 600), token("ALICUOTA IVA", 200, 600, 110),
              token("IVA", 340, 600, 40), token("PERCEPCIONES IVA", 460, 600, 160),
              token("PERCEPCIONES OTROS", 700, 600, 180),
              token(net, 90, 640), token("(21.00)", 220, 640), token(vat, 335, 640),
              token("TOTAL", 600, 680), token(total, 810, 680)]
    if other is not None:
        tokens.append(token(other, 720, 640))
    return document(tokens, alternatives)


class AmountTests(unittest.TestCase):
    def test_argentine_grouping_and_decimal_unit_prices(self):
        self.assertEqual(normalizar_importe("186.300"), 186300)
        self.assertEqual(normalizar_importe("186.300,00"), 186300)
        self.assertEqual(normalizar_importe("6400.0000"), 6400)

    def test_headers_on_one_row_do_not_become_amounts(self):
        amounts = inferir_importes(money_document())
        self.assertEqual([amounts[k]["valor"] for k in ("neto", "iva", "importe_otros_tributos", "total")], [100, 21, 0, 121])
        self.assertEqual(amounts["_alertas"], [])

    def test_supported_alternative_wins_over_inconsistent_digit(self):
        doc = money_document(net="108,00", vat="81,00", alternatives=[
            token("100,00", 90, 640, confidence=.7), token("21,00", 335, 640, confidence=.8)])
        amounts = inferir_importes(doc)
        self.assertEqual((amounts["neto"]["valor"], amounts["iva"]["valor"]), (100, 21))

    def test_exact_cents_agreement_beats_higher_ocr_scores(self):
        doc = money_document(vat="21,08", total="121,10", alternatives=[
            token("21,00", 335, 640, confidence=.7),
            token("Son Pesos ciento veintiuno", 150, 750, 400, confidence=.8)])
        amounts = inferir_importes(doc)
        self.assertEqual((amounts["iva"]["valor"], amounts["total"]["valor"]), (21, 121))

    def test_explicit_other_taxes_are_preserved(self):
        amounts = inferir_importes(money_document(other="3,00", total="124,00"))
        self.assertEqual(amounts["importe_otros_tributos"]["valor"], 3)
        self.assertEqual(amounts["_alertas"], [])

    def test_contradiction_is_not_overwritten_to_make_total_match(self):
        doc = money_document(net="9,00", vat="21,00", total="121,00")
        amounts = inferir_importes(doc)
        self.assertEqual(amounts["neto"]["valor"], 9)
        self.assertEqual(amounts["iva"]["valor"], 21)
        invoice = parsear_factura(doc)
        self.assertEqual(validar_factura(invoice)[0], "REVISAR")
        self.assertTrue(invoice["_alertas_extraccion"])

    def test_missing_vat_header_is_recovered_from_another_pass(self):
        doc = money_document()
        doc["tokens"] = [t for t in doc["tokens"] if not (t["texto"] == "IVA" and t["y"] == 600)]
        doc = document(doc["tokens"], [token("SUBTOTAL", 80, 600, reading="retry"),
                                      token("ALICUOTA IVA", 200, 600, 110, reading="retry"),
                                      token("IVA", 340, 600, 40, reading="retry"),
                                      token("PERCEPCIONES OTROS", 700, 600, 180, reading="retry")])
        self.assertEqual(inferir_importes(doc)["iva"]["valor"], 21)

    def test_unreadable_table_header_prevents_fallback_invention(self):
        doc = money_document()
        doc = document([t for t in doc["tokens"] if not (t["texto"] == "IVA" and t["y"] == 600)])
        amounts = inferir_importes(doc)
        self.assertIsNone(amounts["iva"]["valor"])
        self.assertTrue(amounts["_alertas"])

    def test_multiple_tax_rows_are_added_without_first_rate_overwrite(self):
        doc = money_document(total="181,50")
        doc["tokens"].extend([token("50,00", 90, 660), token("(21.00)", 220, 660), token("10,50", 335, 660)])
        doc = document(doc["tokens"])
        amounts = inferir_importes(doc)
        self.assertEqual((amounts["neto"]["valor"], amounts["iva"]["valor"]), (150, 31.5))

    def test_item_subtotal_requires_vat_and_total_corroboration(self):
        doc = money_document(net="109,00")
        items = [token("CANTIDAD", 80, 300), token("DESCRIPCION", 300, 300),
                 token("PRECIO UNITARIO", 650, 300, 120), token("ALICUOTA IVA", 850, 300, 100),
                 token("1.000", 80, 330), token("Repuesto", 300, 330), token("60.0000", 670, 330),
                 token("(21.00)", 850, 330), token("1.000", 80, 350),
                 token("Servicio", 300, 350), token("40.0000", 670, 350), token("(21.00)", 850, 350)]
        doc = document(items + doc["tokens"])
        amounts = inferir_importes(doc)
        self.assertEqual(amounts["neto"]["valor"], 100)
        self.assertEqual(amounts["neto"]["origen"], "INFERENCIA_ITEMS")
        doc["tokens"] = [t for t in doc["tokens"] if t["texto"] != "121,00"] + [token("999,00", 810, 680)]
        doc = document(doc["tokens"])
        amounts = inferir_importes(doc)
        self.assertEqual(amounts["neto"]["valor"], 109)
        self.assertTrue(amounts["_alertas"])

    def test_discount_column_disables_item_subtotal_inference(self):
        doc = money_document(net="109,00")
        items = [token("CANTIDAD", 80, 300), token("DESCRIPCION", 300, 300),
                 token("PRECIO UNITARIO", 650, 300, 120), token("BONIFICACION", 850, 300, 100),
                 token("1.000", 80, 330), token("Servicio", 300, 330), token("100.0000", 670, 330)]
        amounts = inferir_importes(document(items + doc["tokens"]))
        self.assertEqual(amounts["neto"]["valor"], 109)
        self.assertTrue(amounts["_alertas"])

    def test_plain_text_keeps_contradictory_printed_vat(self):
        doc = {"texto": "Importe Neto Gravado: 100,00\nIVA 21%: 99,00\nImporte Total: 121,00"}
        amounts = inferir_importes(doc)
        self.assertEqual(amounts["iva"]["valor"], 99)
        self.assertEqual(validar_factura(parsear_factura(doc))[0], "REVISAR")

    def test_percentage_is_not_read_as_vat_amount(self):
        amounts = inferir_importes({"texto": "Importe Neto Gravado: 100,00\nIVA 21%\nImporte Total: 121,00"})
        self.assertEqual(amounts["iva"]["valor"], 21)
        self.assertEqual(amounts["iva"]["origen"], "INFERENCIA_MATEMATICA")

    def test_amount_in_words_requires_complete_supported_text(self):
        self.assertEqual(_total_in_words("Son Pesos doscientos veinticinco mil cuatrocientos veintitres.-"), 225423)
        self.assertEqual(_total_in_words("Son Pesos cien con 25/100"), 100.25)
        self.assertIsNone(_total_in_words("Son Pesos cien con"))
        self.assertIsNone(_total_in_words("Son Pesos cien importe ilegible"))


class DetailTests(unittest.TestCase):
    def test_table_can_be_above_fixed_detail_zone_and_excludes_footer(self):
        tokens = [token("CANTIDAD", 100, 260), token("DESCRIPCION", 300, 260, 150),
                  token("PRECIO UNITARIO", 650, 260, 180),
                  token("1.000", 100, 290), token("005-PREFILTRO DE COMBUSTIBLE()", 260, 290, 340),
                  token("100,00", 670, 290), token("1.000", 100, 315),
                  token("1-. junta de escape()", 260, 315, 240), token("20,00", 670, 315),
                  token("SON 1 HOJAS", 100, 600), token("Recibi(mos)", 100, 650)]
        detail = inferir_detalle(document(tokens))
        self.assertEqual(detail["valor"], "005-PREFILTRO DE COMBUSTIBLE | 1-. junta de escape")

    def test_wrapped_description_joins_item_without_watermark(self):
        tokens = [token("CANTIDAD", 100, 260), token("DESCRIPCION", 300, 260, 150),
                  token("PRECIO UNITARIO", 650, 260, 180), token("1.000", 100, 290),
                  token("Servicio de", 260, 290), token("100,00", 670, 290),
                  token("mantenimiento", 260, 310, 140), token("ORIGINAL", 300, 480)]
        self.assertEqual(inferir_detalle(document(tokens))["valor"], "Servicio de mantenimiento")


class RegionTests(unittest.TestCase):
    def test_overlapping_regions_restore_page_coordinates_and_deduplicate(self):
        first = {"tokens": [token("First", 100, 640)], "texto": "First", "motor": "PADDLEOCR"}
        second = {"tokens": [token("First", 100, 20), token("Second", 100, 80)], "texto": "Second", "motor": "PADDLEOCR"}
        with patch("extractor._ocr_con_fallback", side_effect=[first, second]):
            result = _ocr_regiones(Image.new("RGB", (1000, 1200)), 1)
        self.assertEqual([t["texto"] for t in result["tokens"]], ["First", "Second"])
        self.assertEqual(result["tokens"][1]["y"], 700)
        self.assertAlmostEqual(result["tokens"][1]["y_rel"], 700/1200)


if __name__ == "__main__":
    unittest.main()
