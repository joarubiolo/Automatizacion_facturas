"""
Funciones para conectarse a Google Drive y Google Sheets.

V4:
Se agregó la columna "importe_otros_tributos" entre IVA y Total.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Dict, List, Optional

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import (
    INPUT_FOLDER_ID,
    PROCESSED_FOLDER_ID,
    REVIEW_FOLDER_ID,
    SERVICE_ACCOUNT_FILE,
    SPREADSHEET_ID,
    WORKSHEET_NAME,
)

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _crear_credenciales():
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )


credentials = _crear_credenciales()
drive = build("drive", "v3", credentials=credentials)
gc = gspread.authorize(credentials)

spreadsheet = gc.open_by_key(SPREADSHEET_ID)
sheet = spreadsheet.worksheet(WORKSHEET_NAME)


def listar_facturas_entrada() -> List[Dict]:
    query = (
        f"'{INPUT_FOLDER_ID}' in parents "
        "and trashed = false "
        "and mimeType != 'application/vnd.google-apps.folder'"
    )

    resultado = drive.files().list(
        q=query,
        fields="files(id,name,mimeType,createdTime,modifiedTime,size)",
        orderBy="createdTime asc",
        pageSize=1000,
    ).execute()

    return resultado.get("files", [])


def descargar_archivo(file_id: str) -> io.BytesIO:
    request = drive.files().get_media(fileId=file_id)
    archivo = io.BytesIO()
    downloader = MediaIoBaseDownload(archivo, request)

    terminado = False
    while not terminado:
        _, terminado = downloader.next_chunk()

    archivo.seek(0)
    return archivo


def mover_archivo(file_id: str, carpeta_destino_id: str) -> None:
    metadata = drive.files().get(
        fileId=file_id,
        fields="parents",
    ).execute()

    parents_actuales = metadata.get("parents", [])
    remove_parents = ",".join(parents_actuales) if parents_actuales else None

    kwargs = {
        "fileId": file_id,
        "addParents": carpeta_destino_id,
        "fields": "id, parents",
    }

    if remove_parents:
        kwargs["removeParents"] = remove_parents

    drive.files().update(**kwargs).execute()


def mover_a_procesadas(file_id: str) -> None:
    mover_archivo(file_id, PROCESSED_FOLDER_ID)


def mover_a_revisar(file_id: str) -> None:
    mover_archivo(file_id, REVIEW_FOLDER_ID)


def obtener_registros() -> List[Dict]:
    # Conservar la coma decimal y los ceros iniciales de los identificadores.
    # La conversión automática de gspread interpreta "730460,45" como 73046045.
    return sheet.get_all_records(numericise_ignore=["all"])


def factura_ya_registrada(
    drive_id: str,
    hash_archivo: str,
    clave_factura: Optional[str],
) -> bool:
    registros = obtener_registros()

    for registro in registros:
        if str(registro.get("drive_id", "")).strip() == str(drive_id).strip():
            return True

        if str(registro.get("hash", "")).strip() == str(hash_archivo).strip():
            return True

        if clave_factura:
            if str(registro.get("clave_factura", "")).strip() == clave_factura.strip():
                return True

    return False


def guardar_factura(factura: Dict) -> None:
    """
    IMPORTANTE:
    La primera fila del Sheet debe tener EXACTAMENTE estos encabezados:

    fecha_carga, estado, fecha_factura, tipo, punto_venta, numero,
    proveedor, cuit_proveedor, cliente, cuit_cliente, detalle,
    neto, iva, importe_otros_tributos, total, cae, vencimiento_cae,
    archivo, drive_id, hash, clave_factura, observaciones
    """

    fila = [
        factura.get("fecha_carga", datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        factura.get("estado", ""),
        factura.get("fecha_factura", ""),
        factura.get("tipo", ""),
        factura.get("punto_venta", ""),
        factura.get("numero", ""),
        factura.get("proveedor", ""),
        factura.get("cuit_proveedor", ""),
        factura.get("cliente", ""),
        factura.get("cuit_cliente", ""),
        factura.get("detalle", ""),
        factura.get("neto", ""),
        factura.get("iva", ""),

        # NUEVO CAMPO V4
        factura.get("importe_otros_tributos", 0),

        factura.get("total", ""),
        factura.get("cae", ""),
        factura.get("vencimiento_cae", ""),
        factura.get("archivo", ""),
        factura.get("drive_id", ""),
        factura.get("hash", ""),
        factura.get("clave_factura", ""),
        factura.get("observaciones", ""),
    ]

    sheet.append_row(
        fila,
        value_input_option="USER_ENTERED",
    )


def comprobar_conexion() -> Dict[str, str]:
    archivos = listar_facturas_entrada()

    return {
        "sheet": spreadsheet.title,
        "worksheet": sheet.title,
        "archivos_entrada": str(len(archivos)),
    }
