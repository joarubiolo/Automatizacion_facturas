from typing import Dict, Optional

from inference_engine import (
    inferir_factura,
    cuit_es_valido,
    normalizar_cuit,
)


def parsear_factura(documento_o_texto) -> Dict:
    if isinstance(documento_o_texto, dict):
        documento = documento_o_texto
    else:
        documento = {
            "texto": str(documento_o_texto or ""),
            "metodo": "TEXTO_COMPATIBILIDAD",
            "tokens": [],
            "lineas": [],
        }

    return inferir_factura(documento)


def crear_clave_factura(factura: Dict) -> Optional[str]:
    campos = [
        factura.get("cuit_proveedor"),
        factura.get("tipo"),
        factura.get("punto_venta"),
        factura.get("numero"),
    ]

    if not all(campos):
        return None

    return "-".join(str(x).strip() for x in campos)
