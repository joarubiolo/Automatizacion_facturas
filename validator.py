"""
VALIDATOR V5

Mejoras:
- valida CUIT argentino con dígito verificador;
- usa:
      neto + IVA + importe_otros_tributos = total
- mantiene estado REVISAR si faltan datos fiscales críticos.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from parser import cuit_es_valido


def validar_factura(
    factura: Dict,
) -> Tuple[
    str,
    List[str],
]:

    errores: List[str] = []

    # ========================================================
    # DATOS OBLIGATORIOS
    # ========================================================

    if not factura.get(
        "fecha_factura"
    ):
        errores.append(
            "Fecha de factura no detectada"
        )

    if not factura.get(
        "tipo"
    ):
        errores.append(
            "Tipo de factura no detectado"
        )

    if not factura.get(
        "punto_venta"
    ):
        errores.append(
            "Punto de venta no detectado"
        )

    if not factura.get(
        "numero"
    ):
        errores.append(
            "Número de factura no detectado"
        )

    # ========================================================
    # CUIT
    # ========================================================

    cuit_proveedor = factura.get(
        "cuit_proveedor"
    )

    if not cuit_proveedor:

        errores.append(
            "CUIT del proveedor no detectado"
        )

    elif not cuit_es_valido(
        cuit_proveedor
    ):

        errores.append(
            "CUIT del proveedor detectado pero "
            "el dígito verificador es inválido"
        )

    cuit_cliente = factura.get(
        "cuit_cliente"
    )

    if (
        cuit_cliente
        and not cuit_es_valido(
            cuit_cliente
        )
    ):

        errores.append(
            "CUIT del cliente detectado pero "
            "el dígito verificador es inválido"
        )

    # ========================================================
    # IMPORTES
    # ========================================================

    neto = factura.get(
        "neto"
    )

    iva = factura.get(
        "iva"
    )

    total = factura.get(
        "total"
    )

    importe_otros_tributos = float(
        factura.get(
            "importe_otros_tributos"
        )
        or 0
    )

    if neto is None:
        errores.append(
            "Importe neto no detectado"
        )

    if iva is None:
        errores.append(
            "IVA no detectado"
        )

    if total is None:
        errores.append(
            "Total no detectado"
        )

    # ========================================================
    # VALIDACIÓN MATEMÁTICA
    # ========================================================

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
            esperado
            - float(total)
        )

        # Tolerancia mínima por redondeos.
        tolerancia = max(
            1.0,
            abs(float(total))
            * 0.00001,
        )

        if diferencia > tolerancia:

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

    return (
        estado,
        errores,
    )
