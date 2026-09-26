"""
Validaciones automáticas.

No solicita confirmación al usuario:
- Si todo parece correcto -> estado = OK
- Si falta información o hay inconsistencias -> estado = REVISAR
"""

from __future__ import annotations

from typing import Dict, List, Tuple


def validar_cuit(cuit: str | None) -> bool:
    """
    Validación básica de formato.
    Comprueba que tenga exactamente 11 dígitos.

    Más adelante se puede agregar la validación del dígito verificador.
    """
    return bool(cuit and str(cuit).isdigit() and len(str(cuit)) == 11)


def validar_factura(factura: Dict) -> Tuple[str, List[str]]:
    errores: List[str] = []

    if not factura.get("fecha_factura"):
        errores.append("Fecha de factura no detectada")

    if not factura.get("tipo"):
        errores.append("Tipo de factura no detectado")

    if not factura.get("punto_venta"):
        errores.append("Punto de venta no detectado")

    if not factura.get("numero"):
        errores.append("Número de factura no detectado")

    if not validar_cuit(factura.get("cuit_proveedor")):
        errores.append("CUIT del proveedor no detectado o inválido")

    if factura.get("total") is None:
        errores.append("Total no detectado")

    # Si tenemos neto + IVA + total, comprobamos consistencia.
    neto = factura.get("neto")
    iva = factura.get("iva")
    total = factura.get("total")

    if neto is not None and iva is not None and total is not None:
        diferencia = abs((float(neto) + float(iva)) - float(total))

        # Tolerancia de 1 peso para soportar redondeos.
        if diferencia > 1:
            errores.append(
                f"El total no coincide con Neto + IVA "
                f"(diferencia: {diferencia:.2f})"
            )

    estado = "REVISAR" if errores else "OK"

    return estado, errores
