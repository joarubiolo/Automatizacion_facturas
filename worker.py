"""Proceso continuo para una VM: python worker.py [--once]."""

import argparse
from collections import Counter
import logging
import os
from pathlib import Path
import signal
from threading import Event


LOGGER = logging.getLogger("facturas.worker")
REQUIRED_IDS = (
    "INPUT_FOLDER_ID", "PROCESSED_FOLDER_ID", "REVIEW_FOLDER_ID", "SPREADSHEET_ID",
)


def validar_configuracion():
    missing = [key for key in REQUIRED_IDS if not os.getenv(key, "").strip()]
    if missing:
        raise ValueError("Faltan variables: " + ", ".join(missing))
    secret = Path(os.getenv("SERVICE_ACCOUNT_FILE", "credentials/service_account.json"))
    if not secret.is_file():
        raise ValueError("Falta el archivo de credenciales indicado por SERVICE_ACCOUNT_FILE")
    try:
        interval = int(os.getenv("POLL_SECONDS", "60"))
    except ValueError:
        raise ValueError("POLL_SECONDS debe ser un entero positivo") from None
    if interval <= 0:
        raise ValueError("POLL_SECONDS debe ser un entero positivo")
    return interval


def ejecutar_worker(ciclo, stop, interval, once=False):
    """Ejecuta ciclos secuenciales; SIGTERM interrumpe la espera entre ciclos."""
    if interval <= 0:
        raise ValueError("El intervalo debe ser positivo")
    while not stop.is_set():
        exit_code = 0
        try:
            archivos, resultados = ciclo()
            counts = Counter(item["estado"] for item in resultados)
            # Solo cantidades: las facturas y los errores detallados no van al log.
            LOGGER.info(
                "Ciclo: detectadas=%d OK=%d inferidas=%d revisar=%d duplicadas=%d errores=%d",
                len(archivos), counts["OK"], counts["OK_INFERIDO"],
                counts["REVISAR"], counts["DUPLICADO"], counts["ERROR"],
            )
            exit_code = 1 if counts["ERROR"] else 0
        except Exception as exc:
            LOGGER.error("Ciclo fallido (%s); se reintentará en el próximo ciclo", type(exc).__name__)
            exit_code = 1
        if once:
            return exit_code
        stop.wait(interval)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Procesar un ciclo y salir")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        interval = validar_configuracion()
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2

    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    try:
        # Importar después de validar permite diagnosticar configuración sin
        # conectar a Google. Docker reintenta si falla la conexión inicial.
        from pipeline import ejecutar_ciclo
    except Exception as exc:
        LOGGER.error("No se pudo iniciar Google/OCR (%s). Revisar credenciales, permisos y red.", type(exc).__name__)
        return 1

    LOGGER.info("Worker iniciado; intervalo=%ds", interval)
    return ejecutar_worker(ejecutar_ciclo, stop, interval, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
