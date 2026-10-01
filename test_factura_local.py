import io
import sys
from pathlib import Path

from extractor import extraer_documento
from parser import parsear_factura, crear_clave_factura
from validator import validar_factura


def fmt_importe(v):
    if v is None:
        return "-"
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(v)


if len(sys.argv) < 2:
    print('Uso: python test_factura_local.py "ruta/factura.pdf"')
    raise SystemExit(1)

ruta = Path(sys.argv[1])

if not ruta.exists():
    print(f"No existe: {ruta}")
    raise SystemExit(1)

mimes = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

mime = mimes.get(ruta.suffix.lower())

if not mime:
    print("Formato no soportado")
    raise SystemExit(1)

documento = extraer_documento(
    io.BytesIO(ruta.read_bytes()),
    mime,
    ruta.name,
)

factura = parsear_factura(documento)
factura["clave_factura"] = crear_clave_factura(factura)

estado, errores = validar_factura(factura)
meta = factura.get("_meta") or {}

print(f"ARCHIVO: {ruta.name} | METODO: {documento['metodo']}")
print("-" * 105)

campos = (
    "fecha_factura",
    "tipo",
    "punto_venta",
    "numero",
    "proveedor",
    "cuit_proveedor",
    "cliente",
    "cuit_cliente",
    "detalle",
    "neto",
    "iva",
    "importe_otros_tributos",
    "total",
    "cae",
    "vencimiento_cae",
    "clave_factura",
)

for nombre in campos:
    valor = factura.get(nombre)

    if nombre in {"neto", "iva", "importe_otros_tributos", "total"}:
        valor = fmt_importe(valor)
    elif valor in (None, ""):
        valor = "-"

    info = meta.get(nombre) or {}
    conf = float(info.get("confianza", 0) or 0)
    origen = info.get("origen", "-")

    print(
        f"{nombre:<24} {str(valor):<42} "
        f"conf={conf:.2f}  {origen}"
    )

print("-" * 105)
print("ESTADO:", estado)
print("ERRORES:", " | ".join(errores) if errores else "ninguno")
print(
    "INFERIDOS:",
    ", ".join(factura.get("_campos_inferidos") or [])
    or "ninguno",
)
