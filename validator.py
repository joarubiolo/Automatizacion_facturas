from typing import Dict, List, Tuple

from inference_engine import cuit_es_valido


def validar_factura(factura: Dict) -> Tuple[str, List[str]]:
    errores: List[str] = []

    obligatorios = (
        ("fecha_factura", "Fecha de factura no detectada"),
        ("punto_venta", "Punto de venta no detectado"),
        ("numero", "Número de factura no detectado"),
        ("cuit_proveedor", "CUIT del proveedor no detectado"),
        ("neto", "Importe neto no detectado"),
        ("iva", "IVA no detectado"),
        ("total", "Total no detectado"),
    )

    for campo, mensaje in obligatorios:
        if factura.get(campo) in (None, ""):
            errores.append(mensaje)

    if not factura.get("tipo"):
        errores.append("Tipo de factura no detectado")

    cuit_proveedor = factura.get("cuit_proveedor")
    if cuit_proveedor and not cuit_es_valido(cuit_proveedor):
        errores.append("CUIT del proveedor inválido")

    cuit_cliente = factura.get("cuit_cliente")
    if cuit_cliente and not cuit_es_valido(cuit_cliente):
        errores.append("CUIT del cliente inválido")

    neto = factura.get("neto")
    iva = factura.get("iva")
    otros = float(factura.get("importe_otros_tributos") or 0)
    total = factura.get("total")

    if None not in (neto, iva, total):
        esperado = float(neto) + float(iva) + otros
        diferencia = abs(esperado - float(total))
        tolerancia = max(1.0, abs(float(total)) * 0.00001)

        if diferencia > tolerancia:
            errores.append(
                "Total inconsistente con Neto + IVA + Otros Tributos "
                f"(diferencia {diferencia:.2f})"
            )

    meta = factura.get("_meta") or {}

    for campo in (
        "fecha_factura",
        "punto_venta",
        "numero",
        "cuit_proveedor",
        "neto",
        "iva",
        "total",
    ):
        m = meta.get(campo) or {}
        if m.get("valor") is not None and float(m.get("confianza", 0) or 0) < .55:
            errores.append(
                f"Confianza baja en {campo}: {float(m.get('confianza', 0)):.2f}"
            )

    if errores:
        return "REVISAR", errores

    if factura.get("_campos_inferidos"):
        return "OK_INFERIDO", []

    return "OK", []
