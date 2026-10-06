"""Carga y corrección en Sheets, con bloqueo local y comprobación de versiones."""

import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import UUID

from dashboard.invoices import (
    SHEET_FIELDS,
    InvoiceError,
    public_record,
    reference,
    revision,
    validate_invoice,
)


class SheetsStore:
    def __init__(self, sheet=None):
        self.sheet = sheet
        self.lock = RLock()
        self.pending = {}

    def _connect(self):
        if self.sheet is None:
            import gspread
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                os.environ["DASHBOARD_GOOGLE_FILE"], scopes=["https://www.googleapis.com/auth/spreadsheets"])
            client = gspread.authorize(credentials)
            client.set_timeout(15)
            self.sheet = client.open_by_key(os.environ["SPREADSHEET_ID"]).worksheet(os.environ["WORKSHEET_NAME"])
        return self.sheet

    def _rows(self):
        grid = self._connect().get_all_values()
        if not grid or len(set(grid[0])) != len(grid[0]) or not set(SHEET_FIELDS).issubset(grid[0]):
            raise InvoiceError("La planilla necesita los encabezados de facturas del proyecto", 503)
        headers = grid[0]
        return headers, [dict(zip(headers, [*row, *([""] * (len(headers) - len(row)))])) for row in grid[1:]]

    def view(self, records):
        # La escritura se ve de inmediato; el worker sigue sincronizando su copia.
        with self.lock:
            result = list(records)
            for ref, row in list(self.pending.items()):
                match = next((i for i, old in enumerate(result) if reference(old, i) == ref), None)
                if match is not None:
                    if revision(result[match]) == revision(row):
                        del self.pending[ref]
                    else:
                        result[match] = row
                else:
                    result.append(row)
            return result

    def get(self, ref):
        with self.lock:
            _, rows = self._rows()
            matches = [(i, row) for i, row in enumerate(rows) if reference(row, i) == ref]
            if not matches:
                raise InvoiceError("La factura ya no está disponible. Actualizá el historial.", 404)
            if len(matches) != 1:
                raise InvoiceError("Hay registros duplicados. Revisá esta factura en la planilla.", 409)
            index, row = matches[0]
            return public_record(row, index)

    def save(self, payload, ref=None):
        if not isinstance(payload, dict) or set(payload) - {"invoice", "revision", "request_key"}:
            raise InvoiceError("Solicitud inválida")
        values, warnings = validate_invoice(payload.get("invoice"))
        with self.lock:
            headers, rows = self._rows()
            index, old = None, {}
            if ref:
                matches = [(i, row) for i, row in enumerate(rows) if reference(row, i) == ref]
                if len(matches) != 1:
                    raise InvoiceError("La factura cambió de ubicación. Actualizá el historial.", 409)
                index, old = matches[0]
                if not payload.get("revision") or payload["revision"] != revision(old):
                    raise InvoiceError("Otra edición modificó la factura. Volvé a abrirla para ver los datos actuales.", 409)
            else:
                try:
                    request_key = str(UUID(payload.get("request_key", "")))
                except (ValueError, TypeError, AttributeError) as exc:
                    raise InvoiceError("Volvé a abrir el formulario e intentá guardar") from exc
                existing = next((row for row in rows if row.get("hash") == "manual:" + request_key), None)
                if existing:
                    return {"invoice": public_record(existing), "warnings": [], "created": False}
                old = {"fecha_carga": datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S"),
                       "hash": "manual:" + request_key, "drive_id": ""}
            key = values["clave_factura"]
            if key and any(i != index and row.get("clave_factura") == key for i, row in enumerate(rows)):
                raise InvoiceError("Esta factura ya está registrada. Buscala en el historial para corregirla.", 409)
            row = {**old, **values}
            if not row.get("archivo"):
                row["archivo"] = f"Factura {row['tipo'] or 'manual'} {row['punto_venta']}-{row['numero']}"
            cells = [row.get(name, "") for name in headers]
            # RAW mantiene ceros iniciales y guarda textos como textos, nunca fórmulas.
            if index is None:
                self.sheet.append_row(cells, value_input_option="RAW")
                index = len(rows)
            else:
                self.sheet.update([cells], range_name=f"A{index + 2}:{_column(len(headers))}{index + 2}",
                                  value_input_option="RAW")
            self.pending[reference(row, index)] = row
            return {"invoice": public_record(row, index), "warnings": warnings, "created": ref is None}


def _column(number):
    result = ""
    while number:
        number, digit = divmod(number - 1, 26)
        result = chr(65 + digit) + result
    return result
