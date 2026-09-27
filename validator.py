"""
VALIDATOR V3

Cambio principal:
la ecuación de validación pasa a ser:

    Neto + IVA + Importe Otros Tributos = Total

Esto evita confundir percepciones/impuestos adicionales con IVA.
"""

from __future__ import annotations

from typing import Dict, List, Tuple


def validar_cuit(cuit: str | None) -> bool:
    return bool(
        cuit
        and str(cuit).isdigit()
        and len(str(cuit)) == 11
    )


def validar_factura(
    factura: Dict,
) -> Tuple[str, List[str]]:

    errores: List[str] = []

    if not factura.get("fecha_factura"):
        errores.append(
            "Fecha de factura no detectada"
        )

    if not factura.get("tipo"):
        errores.append(
            "Tipo de factura no detectado"
        )

    if not factura.get("punto_venta"):
        errores.append(
            "Punto de venta no detectado"
        )

    if not factura.get("numero"):
        errores.append(
            "Número de factura no detectado"
        )

    if not validar_cuit(
        factura.get("cuit_proveedor")
    ):
        errores.append(
            "CUIT del proveedor no detectado o inválido"
        )

    if factura.get("total") is None:
        errores.append(
            "Total no detectado"
        )

    neto = factura.get("neto")
    iva = factura.get("iva")
    total = factura.get("total")

    importe_otros_tributos = float(
        factura.get("importe_otros_tributos") or 0
    )

    if (
        neto is not None
        and iva is not None
        and total is not None
    ):
        esperado = (
            float(neto)
            + float(iva)
            + importe_otros_tributos
        )

        diferencia = abs(
            esperado - float(total)
        )

        # Tolerancia de $1 por posibles redondeos.
        if diferencia > 1:
            errores.append(
                "El total no coincide con "
                "Neto + IVA + Importe Otros Tributos "
                f"(diferencia: {diferencia:.2f})"
            )

    estado = (
        "REVISAR"
        if errores
        else "OK"
    )

    return estado, errores
