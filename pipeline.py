"""Procesamiento compartido por Streamlit y el worker de Oracle."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime

from extractor import extraer_documento
from google_services import (
    descargar_archivo,
    factura_ya_registrada,
    guardar_factura,
    listar_facturas_entrada,
    mover_a_procesadas,
    mover_a_revisar,
    obtener_registros,
)
from monitoring import publish, sync_records
from parser import crear_clave_factura, parsear_factura
from validator import validar_factura


def calcular_hash(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def procesar_archivo(info_archivo):
    """
    Procesa una sola factura de principio a fin.
    """
    file_id = info_archivo["id"]
    nombre = info_archivo["name"]
    mime_type = info_archivo.get("mimeType", "")

    publish("file_start", drive_id=file_id, archivo=nombre)

    archivo = descargar_archivo(file_id)
    contenido = archivo.getvalue()
    hash_archivo = calcular_hash(contenido)

    # Primero extraemos el texto para poder construir la clave fiscal.
    publish("stage", stage="Leyendo PDF / OCR")
    documento = extraer_documento(
        archivo=archivo,
        mime_type=mime_type,
        nombre_archivo=nombre,
    )

    metodo = documento["metodo"]
    publish("stage", stage="Detectando campos", metodo=metodo)
    factura = parsear_factura(documento)
    clave_factura = crear_clave_factura(factura)

    # Evitamos cargar la misma factura dos veces.
    publish("stage", stage="Verificando duplicados")
    if factura_ya_registrada(
        drive_id=file_id,
        hash_archivo=hash_archivo,
        clave_factura=clave_factura,
    ):
        # Si el archivo ya fue registrado pero sigue en ENTRADA,
        # lo movemos a PROCESADAS para evitar reprocesarlo continuamente.
        mover_a_procesadas(file_id)

        return {
            "archivo": nombre,
            "estado": "DUPLICADO",
            "metodo": metodo,
            "observaciones": "La factura ya estaba registrada",
        }

    estado, errores = validar_factura(factura)

    factura.update(
        {
            "fecha_carga": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),  # noqa: DTZ005 - formato histórico de Sheets
            "estado": estado,
            "archivo": nombre,
            "drive_id": file_id,
            "hash": hash_archivo,
            "clave_factura": clave_factura or "",
            "observaciones": " | ".join(errores),
        }
    )

    # Guardamos SIEMPRE que hayamos podido procesar el archivo.
    # Si faltan datos, aparecerá como REVISAR.
    publish("stage", stage="Guardando en Sheets", estado=estado)
    guardar_factura(factura)

    publish("stage", stage="Organizando en Drive", estado=estado)

    if estado in ("OK", "OK_INFERIDO"):
        mover_a_procesadas(file_id)
    else:
        mover_a_revisar(file_id)

    return {
        "archivo": nombre,
        "estado": estado,
        "metodo": metodo,
        "observaciones": factura["observaciones"],
    }


def ejecutar_ciclo():
    """
    Busca archivos nuevos y los procesa.

    Cada archivo se maneja de forma independiente:
    un error en una factura no detiene las demás.
    """
    archivos = listar_facturas_entrada()
    publish("queue", files=[{"id": item["id"], "archivo": item.get("name", "")}
                            for item in archivos])

    resultados = []

    for info_archivo in archivos:
        try:
            resultado = procesar_archivo(info_archivo)
            resultados.append(resultado)
            publish("result", drive_id=info_archivo["id"], **resultado)

        except Exception as exc:  # noqa: BLE001 - aislar cada factura del resto de la cola
            # Si ocurre un error inesperado, intentamos mover el archivo
            # a 03_REVISAR para que no bloquee el sistema.
            try:
                mover_a_revisar(info_archivo["id"])
            except Exception as move_exc:  # noqa: BLE001 - no ocultar el error original
                logging.getLogger("facturas.worker").warning(
                    "No se pudo mover el archivo a Revisar (%s)", type(move_exc).__name__)

            resultados.append(
                {
                    "archivo": info_archivo.get("name", "Archivo desconocido"),
                    "estado": "ERROR",
                    "metodo": "",
                    "observaciones": str(exc),
                }
            )
            # No copiar mensajes de excepciones: pueden incluir tokens o URLs.
            publish("result", drive_id=info_archivo["id"], archivo=info_archivo.get("name", ""),
                    estado="ERROR", observaciones=type(exc).__name__)

    if os.getenv("MONITOR_DIR"):
        try:
            sync_records(obtener_registros())
        except Exception as exc:  # noqa: BLE001 - error del historial no cambia el resultado fiscal
            publish("heartbeat", history_error=type(exc).__name__)

    return archivos, resultados
