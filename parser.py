"""
Convierte el texto de una factura en datos estructurados.

IMPORTANTE:
Este parser funciona con reglas generales y está preparado para la factura
de ejemplo utilizada durante el desarrollo.

Si tus proveedores usan formatos muy diferentes, probablemente tengas que
agregar reglas específicas. Buscá los comentarios "# AJUSTAR:".
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional


def solo_digitos(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    digitos = re.sub(r"\D", "", valor)
    return digitos or None


def convertir_importe(valor: Optional[str]) -> Optional[float]:
    """
    Convierte importes argentinos:
        34.249.050,00 -> 34249050.00
        34249050,00    -> 34249050.00
    """
    if not valor:
        return None

    valor = valor.strip().replace("$", "").replace(" ", "")

    # Formato argentino con coma decimal.
    if "," in valor:
        valor = valor.replace(".", "")
        valor = valor.replace(",", ".")
    else:
        # Si no hay coma, quitamos puntos usados como separadores de miles.
        partes = valor.split(".")
        if len(partes) > 2:
            valor = "".join(partes)

    try:
        return float(valor)
    except ValueError:
        return None


def _buscar_primero(patrones: List[str], texto: str, flags=re.IGNORECASE | re.MULTILINE):
    for patron in patrones:
        match = re.search(patron, texto, flags)
        if match:
            return match.group(1).strip()
    return None


def _buscar_importe_por_etiqueta(texto: str, etiquetas: List[str]) -> Optional[float]:
    """
    Busca un importe cerca de etiquetas como "Total General", "IVA", "Sub-Total".
    """
    patron_importe = r"([0-9][0-9\.\,]*[\,\.][0-9]{2})"

    for etiqueta in etiquetas:
        patrones = [
            rf"{etiqueta}\s*:?\s*\$?\s*{patron_importe}",
            rf"{etiqueta}\s*:?.{{0,40}}?\$?\s*{patron_importe}",
        ]

        for patron in patrones:
            match = re.search(
                patron,
                texto,
                re.IGNORECASE | re.MULTILINE | re.DOTALL,
            )
            if match:
                return convertir_importe(match.group(1))

    return None


def _detectar_tipo_factura(texto: str) -> Optional[str]:
    match = re.search(
        r"FACTURA\s+([ABCEM])\b",
        texto,
        re.IGNORECASE,
    )
    return match.group(1).upper() if match else None


def _detectar_numero_factura(texto: str):
    """
    Intenta obtener punto de venta y número.

    Ejemplo:
        N° 0003 00000233
        0003-00000233
    """
    patrones = [
        r"(?:N[°ºo.]?\s*)?(\d{4})\s*[- ]\s*(\d{8})",
        r"(?:N[°ºo.]?\s*)?(\d{4})\s+(\d{8})",
    ]

    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)

    return None, None


def _detectar_cuits(texto: str) -> List[str]:
    """
    Busca CUIT con o sin guiones.

    NOTA:
    En muchas facturas el primer CUIT pertenece al proveedor y el segundo
    al cliente. Esa es la heurística utilizada aquí.
    """
    encontrados = re.findall(
        r"(?<!\d)(\d{2}[- ]?\d{8}[- ]?\d)(?!\d)",
        texto,
    )

    resultado = []
    for cuit in encontrados:
        cuit_limpio = solo_digitos(cuit)
        if cuit_limpio and len(cuit_limpio) == 11 and cuit_limpio not in resultado:
            resultado.append(cuit_limpio)

    return resultado


def _detectar_fechas(texto: str) -> List[str]:
    fechas = re.findall(
        r"\b\d{2}/\d{2}/\d{4}\b",
        texto,
    )

    # Conserva orden y elimina duplicados.
    resultado = []
    for fecha in fechas:
        if fecha not in resultado:
            resultado.append(fecha)

    return resultado


def _detectar_cae(texto: str) -> Optional[str]:
    patrones = [
        r"(?:N[uú]mero\s+de\s+CAE|CAE)\s*:?\s*(\d{14})",
        r"\b(\d{14})\b",
    ]

    return _buscar_primero(patrones, texto)


def _detectar_cliente(texto: str) -> Optional[str]:
    """
    AJUSTAR:
    Esta regla busca texto después de "Sr:".

    Para la factura de ejemplo detecta "KARPA SA".
    Si tus facturas usan "Cliente:", "Razón Social:", etc.,
    agregá más patrones aquí.
    """
    patrones = [
        r"^\s*Sr\.?\s*:\s*(.+?)\s*$",
        r"^\s*Cliente\s*:\s*(.+?)\s*$",
        r"^\s*Raz[oó]n\s+Social\s*:\s*(.+?)\s*$",
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE | re.MULTILINE,
        )
        if match:
            valor = match.group(1).strip()
            if valor:
                return valor

    return None


def _detectar_detalle(texto: str) -> Optional[str]:
    """
    AJUSTAR:
    Busca una línea que parezca un ítem facturado y que termine con
    cantidad / precio unitario / precio total.

    Está pensada para facturas similares a la factura de ejemplo.
    """
    patron = re.compile(
        r"^(.+?)\s+"
        r"\d{1,3}(?:[.,]\d{3})?\s+"
        r"\d[\d\.,]*\s+"
        r"\d[\d\.,]*$",
        re.MULTILINE,
    )

    for match in patron.finditer(texto):
        detalle = match.group(1).strip()

        # Evita tomar encabezados de tabla.
        if "detalle" not in detalle.lower() and len(detalle) > 5:
            return detalle

    return None


def parsear_factura(texto: str) -> Dict:
    """
    Devuelve un diccionario estándar con los campos principales.
    """
    tipo = _detectar_tipo_factura(texto)
    punto_venta, numero = _detectar_numero_factura(texto)

    fechas = _detectar_fechas(texto)
    cuits = _detectar_cuits(texto)

    # Heurística general:
    # 1er CUIT = proveedor/emisor
    # 2do CUIT = cliente
    cuit_proveedor = cuits[0] if len(cuits) >= 1 else None
    cuit_cliente = cuits[1] if len(cuits) >= 2 else None

    fecha_factura = fechas[0] if fechas else None

    # AJUSTAR:
    # En la factura de ejemplo la segunda fecha suele corresponder
    # al vencimiento del CAE.
    vencimiento_cae = fechas[1] if len(fechas) >= 2 else None

    neto = _buscar_importe_por_etiqueta(
        texto,
        [r"Sub[- ]?Total", r"Neto(?:\s+Gravado)?"],
    )

    iva = _buscar_importe_por_etiqueta(
        texto,
        [r"\bIVA\b"],
    )

    total = _buscar_importe_por_etiqueta(
        texto,
        [r"Total\s+General", r"\bTotal\b"],
    )

    factura = {
        "fecha_factura": fecha_factura,
        "tipo": tipo,
        "punto_venta": punto_venta,
        "numero": numero,

        # AJUSTAR:
        # Detectar automáticamente el nombre del proveedor es muy dependiente
        # del diseño de cada factura. Lo dejamos vacío si no hay una regla segura.
        "proveedor": None,
        "cuit_proveedor": cuit_proveedor,

        "cliente": _detectar_cliente(texto),
        "cuit_cliente": cuit_cliente,

        "detalle": _detectar_detalle(texto),

        "neto": neto,
        "iva": iva,
        "total": total,

        "cae": _detectar_cae(texto),
        "vencimiento_cae": vencimiento_cae,
    }

    return factura


def crear_clave_factura(factura: Dict) -> Optional[str]:
    """
    Genera una clave para detectar duplicados:
        CUIT-TIPO-PUNTO_VENTA-NUMERO
    """
    campos = [
        factura.get("cuit_proveedor"),
        factura.get("tipo"),
        factura.get("punto_venta"),
        factura.get("numero"),
    ]

    if not all(campos):
        return None

    return "-".join(str(campo).strip() for campo in campos)
