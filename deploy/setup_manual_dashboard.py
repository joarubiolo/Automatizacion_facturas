"""Prepara el secreto de Sheets para la carga manual, sin mostrar credenciales."""

import json
import os
from pathlib import Path


def setup():
    if os.name != "posix" or os.geteuid() != 0:
        raise RuntimeError("Ejecutar con sudo python3 deploy/setup_manual_dashboard.py en la VM")
    root = Path(__file__).resolve().parents[1]
    source = root / "credentials" / "service_account.json"
    data = source.read_bytes()
    if json.loads(data).get("type") != "service_account":
        raise ValueError("Se necesita el archivo de la cuenta de servicio del proyecto")
    private = root / ".local"
    private.mkdir(exist_ok=True)
    target = private / "dashboard_service_account.json"
    # Crear restringido desde el primer byte, también si se actualiza el secreto.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o600)
        os.fchown(output.fileno(), 10001, 10001)
        output.write(data)
    print("Secreto de Sheets preparado para el panel con permisos 600 y usuario 10001.")


if __name__ == "__main__":
    setup()
