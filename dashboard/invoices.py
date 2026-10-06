"""Importes y campos de facturas; no carga OCR ni conecta a servicios externos."""

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

AMOUNTS = ("neto", "iva", "importe_otros_tributos", "total")
EDITABLE = ("fecha_factura", "tipo", "punto_venta", "numero", "proveedor", "cuit_proveedor",
            "cliente", "cuit_cliente", "detalle", *AMOUNTS, "cae", "vencimiento_cae",
            "archivo", "observaciones", "estado")
SHEET_FIELDS = ("fecha_carga", "estado", "fecha_factura", "tipo", "punto_venta", "numero",
                "proveedor", "cuit_proveedor", "cliente", "cuit_cliente", "detalle", *AMOUNTS,
                "cae", "vencimiento_cae", "archivo", "drive_id", "hash", "clave_factura", "observaciones")


class InvoiceError(Exception):
    def __init__(self, message, status=422, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def amount(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("Importe inválido")
    text = str(value).strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not re.fullmatch(r"-?\d+(?:[.,]\d+)*", text):
        raise ValueError("Ingresá un importe, por ejemplo 730.460,45")
    native = isinstance(value, (int, float, Decimal))
    if not native and "," in text:
        if text.count(",") != 1:
            raise ValueError("Usá una sola coma decimal")
        text = text.replace(".", "").replace(",", ".")
    elif not native and (text.count(".") > 1 or ("." in text and len(text.rsplit(".", 1)[1]) == 3)):
        text = text.replace(".", "")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Importe inválido") from exc
    if not number.is_finite() or abs(number) > Decimal("99999999999.99"):
        raise ValueError("Importe fuera de rango")
    if number != number.quantize(Decimal(".01")):
        raise ValueError("Usá hasta dos decimales")
    return number.quantize(Decimal(".01"))


def invoice_date(value):
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), pattern).date()  # noqa: DTZ007 - fecha de emisión sin hora
        except (TypeError, ValueError):
            pass
    return None


def revision(row):
    values = {key: str(row.get(key, "") or "") for key in SHEET_FIELDS}
    for key in AMOUNTS:
        try:
            number = amount(row.get(key))
            values[key] = str(number) if number is not None else ""
        except ValueError:
            pass
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reference(row, index=0):
    identity = [str(row.get(key, "") or "") for key in ("drive_id", "hash")]
    if not any(identity):
        identity += [str(index), str(row.get("fecha_carga", ""))]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def public_record(row, index=0):
    return {**{key: row.get(key, "") for key in SHEET_FIELDS if key not in {"hash", "clave_factura"}},
            "_ref": reference(row, index), "_revision": revision(row)}


def period_records(records, month="", year=""):
    try:
        if month and not 1 <= int(month) <= 12:
            raise ValueError
        if year and not 1900 <= int(year) <= 2200:
            raise ValueError
    except ValueError as exc:
        raise InvoiceError("Seleccioná un mes y un año válidos", 400) from exc
    if not month and not year:
        return records
    return [row for row in records if (date := invoice_date(row.get("fecha_factura")))
            and (not month or date.month == int(month)) and (not year or date.year == int(year))]


def summarize(records):
    totals = dict.fromkeys(AMOUNTS, Decimal("0.00"))
    missing_total = 0
    for row in records:
        for key in AMOUNTS:
            try:
                number = amount(row.get(key))
            except (TypeError, ValueError):
                number = None
            if number is not None:
                totals[key] += number
            elif key == "total":
                missing_total += 1
    return {"amounts": {key: str(value) for key, value in totals.items()}, "count": len(records),
            "missing_total": missing_total, "missing_date": sum(not invoice_date(row.get("fecha_factura")) for row in records),
            "counts": dict(Counter(str(row.get("estado", "")) for row in records))}


def valid_cuit(value):
    check = 11 - sum(int(n) * weight for n, weight in zip(value[:10], (5, 4, 3, 2, 7, 6, 5, 4, 3, 2))) % 11
    return int(value[-1]) == (0 if check == 11 else 9 if check == 10 else check)


def validate_invoice(data):
    if not isinstance(data, dict) or set(data) - set(EDITABLE):
        raise InvoiceError("Los campos de la factura no son válidos")
    values, errors, warnings = {}, {}, []
    for key in EDITABLE:
        value = data.get(key, "")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            errors[key] = "Ingresá un valor válido"
            continue
        text = str(value).strip()
        limit = 5000 if key == "detalle" else 2000 if key == "observaciones" else 250
        if len(text) > limit:
            errors[key] = f"Usá hasta {limit} caracteres"
        values[key] = text
    for key in AMOUNTS:
        try:
            number = amount(data.get(key, ""))
            if number is not None and number < 0:
                raise ValueError("El importe debe ser mayor o igual a cero")
            values[key] = float(number) if number is not None else ""
        except (TypeError, ValueError) as exc:
            errors[key] = str(exc)
    for key in ("fecha_factura", "vencimiento_cae"):
        if values.get(key):
            date = invoice_date(values[key])
            if not date:
                errors[key] = "Ingresá una fecha válida"
            else:
                values[key] = date.strftime("%d/%m/%Y")
    for key, length in (("punto_venta", 5), ("numero", 8)):
        if values.get(key):
            if not re.fullmatch(rf"\d{{1,{length}}}", values[key]):
                errors[key] = f"Ingresá hasta {length} dígitos"
            else:
                values[key] = values[key].zfill(length)
    for key in ("cuit_proveedor", "cuit_cliente"):
        if values.get(key):
            values[key] = values[key].replace("-", "").replace(" ", "")
            if not re.fullmatch(r"\d{11}", values[key]):
                errors[key] = "El CUIT debe tener 11 dígitos"
            elif not valid_cuit(values[key]):
                warnings.append("CUIT inválido: " + ("proveedor" if key == "cuit_proveedor" else "cliente"))
    if values.get("tipo") not in ("", "A", "B", "C", "E", "M", "T"):
        errors["tipo"] = "Seleccioná un tipo válido"
    if values.get("cae") and not re.fullmatch(r"\d{14}", values["cae"]):
        errors["cae"] = "El CAE debe tener 14 dígitos"
    if values.get("estado") not in ("", "OK", "REVISAR", "OK_INFERIDO"):
        errors["estado"] = "Seleccioná un resultado válido"
    for key in ("fecha_factura", "proveedor", "total"):
        if values.get(key) in (None, ""):
            errors[key] = "Este campo es obligatorio"
    if errors:
        raise InvoiceError("Revisá los campos señalados", fields=errors)
    for key in ("tipo", "punto_venta", "numero", "cuit_proveedor", "neto", "iva"):
        if values.get(key) == "":
            warnings.append("Falta completar " + key.replace("_", " "))
    if all(values[key] != "" for key in AMOUNTS):
        expected = sum(amount(values[key]) for key in AMOUNTS[:3])
        if abs(expected - amount(values["total"])) > Decimal(".02"):
            warnings.append("Neto + IVA + Otros no coincide con el total")
    values["estado"] = "REVISAR" if warnings or values["estado"] == "REVISAR" else "OK"
    fiscal = ("cuit_proveedor", "tipo", "punto_venta", "numero")
    values["clave_factura"] = "-".join(values[key] for key in fiscal) if all(values[key] for key in fiscal) else ""
    return values, warnings
