"""
Funciones para conectarse a Google Drive y Google Sheets.

Normalmente NO necesitás cambiar este archivo.
Los IDs, nombres y credenciales se configuran en config.py.
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
    """
    Crea las credenciales a partir del JSON de la Service Account.
    """
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )


credentials = _crear_credenciales()

# Cliente Google Drive
drive = build("drive", "v3", credentials=credentials)

# Cliente Google Sheets
gc = gspread.authorize(credentials)

# Abrimos el Sheet por ID para evitar problemas si hay dos archivos con el mismo nombre.

print("===================================")
print("DIAGNOSTICO GOOGLE")
print("SPREADSHEET_ID:", repr(SPREADSHEET_ID))
print("SERVICE ACCOUNT:", credentials.service_account_email)
print("===================================")

spreadsheet = gc.open_by_key(SPREADSHEET_ID)
sheet = spreadsheet.worksheet(WORKSHEET_NAME)


def listar_facturas_entrada() -> List[Dict]:
    """
    Devuelve todos los archivos actualmente presentes en 01_ENTRADA.
    Ignora carpetas y archivos enviados a la papelera.
    """
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
    """
    Descarga un archivo de Google Drive a memoria RAM.
    """
    request = drive.files().get_media(fileId=file_id)
    archivo = io.BytesIO()

    downloader = MediaIoBaseDownload(archivo, request)

    terminado = False
    while not terminado:
        _, terminado = downloader.next_chunk()

    archivo.seek(0)
    return archivo


def mover_archivo(file_id: str, carpeta_destino_id: str) -> None:
    """
    Mueve un archivo desde su carpeta actual hacia la carpeta destino.
    """
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
    """
    Lee todos los registros existentes en la pestaña FACTURAS.

    Para una PyME con cientos o algunos miles de facturas es suficiente.
    Si la planilla crece mucho, más adelante conviene optimizar esta búsqueda.
    """
    return sheet.get_all_records()


def factura_ya_registrada(
    drive_id: str,
    hash_archivo: str,
    clave_factura: Optional[str],
) -> bool:
    """
    Evita duplicados utilizando:
    1) ID del archivo de Drive
    2) SHA-256 del archivo
    3) Clave fiscal: CUIT + tipo + punto de venta + número
    """
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
    Agrega una nueva fila en Google Sheets.

    IMPORTANTE:
    La primera fila del Sheet debe tener EXACTAMENTE estos encabezados:
    fecha_carga, estado, fecha_factura, tipo, punto_venta, numero,
    proveedor, cuit_proveedor, cliente, cuit_cliente, detalle,
    neto, iva, total, cae, vencimiento_cae, archivo, drive_id,
    hash, clave_factura, observaciones
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
    """
    Función auxiliar utilizada por test_conexion.py.
    Devuelve información sencilla para comprobar que Drive y Sheets responden.
    """
    archivos = listar_facturas_entrada()

    return {
        "sheet": spreadsheet.title,
        "worksheet": sheet.title,
        "archivos_entrada": str(len(archivos)),
    }
