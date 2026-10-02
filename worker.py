"""Proceso continuo para una VM: python worker.py [--once]."""

import argparse
import logging
import os
import signal
from collections import Counter
from pathlib import Path
from threading import Event

from monitoring import publish, start_monitor

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
            publish("cycle_end", counts=dict(counts), detected=len(archivos))
        except Exception as exc:  # noqa: BLE001 - el servicio debe reintentar sin publicar datos privados
            LOGGER.error("Ciclo fallido (%s); se reintentará en el próximo ciclo", type(exc).__name__)
            exit_code = 1
            publish("cycle_error", error=type(exc).__name__)
        if once:
            return exit_code
        stop.wait(interval)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Procesar un ciclo y salir")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Paddle cambia el nivel del logger raíz a WARNING al cargar los modelos.
    # Un nivel propio mantiene visibles los resúmenes y no altera sus logs.
    LOGGER.setLevel(logging.INFO)
    try:
        interval = validar_configuracion()
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2

    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    publish("start", interval=interval)
    start_monitor(stop)

    try:
        # Importar después de validar permite diagnosticar configuración sin
        # conectar a Google. Docker reintenta si falla la conexión inicial.
        from pipeline import ejecutar_ciclo
    except Exception as exc:  # noqa: BLE001 - Docker reintenta cualquier fallo de inicio
        LOGGER.error("No se pudo iniciar Google/OCR (%s). Revisar credenciales, permisos y red.", type(exc).__name__)
        publish("cycle_error", error=type(exc).__name__)
        stop.set()
        return 1

    LOGGER.info("Worker iniciado; intervalo=%ds", interval)
    try:
        return ejecutar_worker(ejecutar_ciclo, stop, interval, once=args.once)
    finally:
        stop.set()
        publish("stop")


if __name__ == "__main__":
    raise SystemExit(main())
