"""Configura el panel en la VM. Nunca imprime la contraseña ni modifica Google."""

import argparse
import hashlib
import json
import os
import re
import secrets
from pathlib import Path


def setup(domain):
    if not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", domain) or "." not in domain:
        raise ValueError("Indicar un hostname, sin protocolo ni ruta")
    root = Path(__file__).resolve().parents[1]
    private = root / ".local"
    private.mkdir(exist_ok=True)
    auth_file = private / "dashboard_auth.json"
    access_file = private / "PANEL_ACCESO.txt"
    if not auth_file.exists():
        password = secrets.token_urlsafe(24)
        salt = secrets.token_hex(16)
        iterations = 600000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        auth = {"username": "facturas", "password_hash": f"pbkdf2:sha256:{iterations}${salt}${digest}",
                "session_secret": secrets.token_urlsafe(64)}
        auth_file.write_text(json.dumps(auth), encoding="utf-8")
        os.chmod(auth_file, 0o600)
        access_file.write_text(f"Panel: https://{domain}\nUsuario: facturas\nContraseña: {password}\n",
                               encoding="utf-8")
        os.chmod(access_file, 0o600)
    env_file = root / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines()
    replacements = {"DASHBOARD_DOMAIN": domain,
                    "COMPOSE_FILE": "compose.oracle.yaml:.local/compose.instance.yaml:compose.dashboard.yaml"}
    new_lines = []
    for line in lines:
        key = line.split("=", 1)[0]
        if key in replacements:
            new_lines.append(f"{key}={replacements.pop(key)}")
        else:
            new_lines.append(line)
    new_lines.extend(f"{key}={value}" for key, value in replacements.items())
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    print("Configuración preparada. Acceso privado en .local/PANEL_ACCESO.txt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain")
    setup(parser.parse_args().domain)
