"""
TEST LOCAL V5

Uso:
    python test_factura_local.py "ruta/a/factura.pdf"

No escribe nada en Google Sheets.
Sirve solamente para ver qué detectaría el sistema.
"""

import io
import json
import sys
from pathlib import Path

from extractor import extraer_texto
from parser import (
    parsear_factura,
    crear_clave_factura,
)
from validator import validar_factura


if len(sys.argv) < 2:
    print(
        'Uso: python test_factura_local.py "factura.pdf"'
    )
    raise SystemExit(1)


ruta = Path(
    sys.argv[1]
)


if not ruta.exists():
    print(
        f"No existe: {ruta}"
    )
    raise SystemExit(1)


contenido = ruta.read_bytes()


extension = ruta.suffix.lower()


if extension == ".pdf":
    mime_type = "application/pdf"

elif extension in {
    ".jpg",
    ".jpeg",
}:
    mime_type = "image/jpeg"

elif extension == ".png":
    mime_type = "image/png"

else:
    print(
        "Formato no soportado"
    )
    raise SystemExit(1)


texto, metodo = extraer_texto(
    io.BytesIO(contenido),
    mime_type,
    ruta.name,
)


factura = parsear_factura(
    texto
)


factura["clave_factura"] = (
    crear_clave_factura(
        factura
    )
)


estado, errores = validar_factura(
    factura
)


print("\n============================")
print("METODO")
print("============================")
print(metodo)


print("\n============================")
print("RESULTADO")
print("============================")

print(
    json.dumps(
        factura,
        ensure_ascii=False,
        indent=2,
    )
)


print("\n============================")
print("VALIDACION")
print("============================")

print(
    "ESTADO:",
    estado,
)

print(
    "ERRORES:",
    errores,
)


print("\n============================")
print("OCR / TEXTO EXTRAIDO")
print("============================")

print(texto)
