"""
Parser V2 para facturas.

La mejora principal es que NO asocia datos solo por "el primer número
que aparece después de una palabra".

Busca etiquetas concretas:
- Fecha:
- N°
- CUIT
- Sr:
- Sub-Total
- IVA
- Total General
- Numero de CAE
- Fecha Vencimiento CAE

Está diseñado para funcionar junto con extractor.py V2,
que usa PyMuPDF con sort=True.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional


# ============================================================
# OPCIONAL: PROVEEDORES CONOCIDOS
# ============================================================
#
# El nombre del emisor puede estar dentro de un LOGO y no existir
# en el texto digital del PDF.
#
# La forma más fiable de resolverlo es por CUIT.
#
# Podés agregar proveedores aquí:
#
PROVEEDORES_POR_CUIT = {
    # EJEMPLO:
    # "27329850027": "M.C Servicios",
}


def solo_digitos(
    valor: Optional[str],
) -> Optional[str]:

    if not valor:
        return None

    digitos = re.sub(r"\D", "", valor)

    return digitos or None


def convertir_importe(
    valor: Optional[str],
) -> Optional[float]:
    """
    Convierte:
        34.249.050,00 -> 34249050.00
        34249050,00    -> 34249050.00
    """

    if not valor:
        return None

    valor = (
        valor.strip()
        .replace("$", "")
        .replace(" ", "")
    )

    if "," in valor:
        valor = valor.replace(".", "")
        valor = valor.replace(",", ".")

    try:
        return float(valor)

    except ValueError:
        return None


def _buscar_primero(
    patrones: List[str],
    texto: str,
) -> Optional[str]:

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE | re.MULTILINE,
        )

        if match:
            return match.group(1).strip()

    return None


# ============================================================
# TIPO DE FACTURA
# ============================================================

def _detectar_tipo_factura(
    texto: str,
) -> Optional[str]:

    match = re.search(
        r"\bFACTURA\s+([ABCEM])\b",
        texto,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1).upper()


# ============================================================
# PUNTO DE VENTA + NÚMERO
# ============================================================

def _detectar_numero_factura(
    texto: str,
):
    """
    Busca expresamente el bloque N°.

    Ejemplos:
        N° 0003 00000233
        N° 0003-00000233

    Esto evita interpretar:
        8000
    como punto de venta.
    """

    patrones = [
        r"N[°ºo.]?\s*(\d{4})\s*[- ]+\s*(\d{8})",
        r"N[°ºo.]?\s*\n?\s*(\d{4})\s*\n?\s*(\d{8})",
    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE,
        )

        if match:
            return (
                match.group(1),
                match.group(2),
            )

    return None, None


# ============================================================
# FECHAS
# ============================================================

def _detectar_fecha_factura(
    texto: str,
) -> Optional[str]:
    """
    Busca "Fecha:" evitando confundirla con
    "Fecha Vencimiento CAE".
    """

    patrones = [
        r"^\s*Fecha\s*:\s*(\d{2}/\d{2}/\d{4})",
        r"\bFecha\s*:\s*(\d{2}/\d{2}/\d{4})",
    ]

    return _buscar_primero(
        patrones,
        texto,
    )


def _detectar_vencimiento_cae(
    texto: str,
) -> Optional[str]:

    return _buscar_primero(
        [
            r"Fecha\s+Vencimiento\s+CAE\s*:\s*(\d{2}/\d{2}/\d{4})",
        ],
        texto,
    )


# ============================================================
# CUIT
# ============================================================

def _detectar_cuits(
    texto: str,
) -> List[str]:

    encontrados = re.findall(
        r"(?<!\d)(\d{11})(?!\d)",
        texto,
    )

    resultado = []

    for cuit in encontrados:

        if cuit not in resultado:
            resultado.append(cuit)

    return resultado


def _detectar_cuit_cliente(
    texto: str,
) -> Optional[str]:
    """
    Busca el CUIT que aparece junto al bloque del cliente.

    Ejemplo:
        Sr: KARPA SA   CUIT: 30561286686
    """

    patron = (
        r"\bSr\.?\s*:"
        r".{0,200}?"
        r"\bCUIT\s*:\s*(\d{11})"
    )

    match = re.search(
        patron,
        texto,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        return match.group(1)

    return None


def _detectar_cuit_proveedor(
    texto: str,
    cuit_cliente: Optional[str],
) -> Optional[str]:
    """
    Para el emisor prioriza un CUIT que:
    - sea distinto al del cliente;
    - aparezca varias veces;
    - esté cerca de Ingresos Brutos / Inicio Actividades.

    Es más seguro que asumir "primer CUIT = proveedor".
    """

    candidatos = re.findall(
        r"(?<!\d)(\d{11})(?!\d)",
        texto,
    )

    candidatos = [
        cuit
        for cuit in candidatos
        if cuit != cuit_cliente
    ]

    if not candidatos:
        return None

    # El CUIT del emisor suele repetirse.
    conteo = Counter(candidatos)

    return conteo.most_common(1)[0][0]


# ============================================================
# CLIENTE
# ============================================================

def _detectar_cliente(
    texto: str,
) -> Optional[str]:
    """
    Captura solamente el nombre después de "Sr:".

    IMPORTANTE:
    se detiene antes de "CUIT:" para no obtener:
        KARPA SA CUIT: 305...
    """

    patrones = [
        (
            r"^\s*Sr\.?\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|\s+CUIT\s*:|$)"
        ),
        (
            r"^\s*Cliente\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|\s+CUIT\s*:|$)"
        ),
        (
            r"^\s*Raz[oó]n\s+Social\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|\s+CUIT\s*:|$)"
        ),
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


# ============================================================
# IMPORTES
# ============================================================

PATRON_IMPORTE = (
    r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}"
    r"|[0-9]+,[0-9]{2})"
)


def _importe_misma_linea(
    texto: str,
    etiqueta: str,
) -> Optional[float]:
    """
    Busca un importe en la MISMA línea que la etiqueta.

    Esto evita que "IVA" tome accidentalmente el subtotal.
    """

    patron = (
        rf"{etiqueta}"
        rf"[^\r\n0-9]*"
        rf"{PATRON_IMPORTE}"
    )

    match = re.search(
        patron,
        texto,
        re.IGNORECASE,
    )

    if not match:
        return None

    return convertir_importe(
        match.group(1)
    )


def _detectar_neto(
    texto: str,
) -> Optional[float]:

    for etiqueta in [
        r"Sub[- ]?Total\s*:",
        r"Neto(?:\s+Gravado)?\s*:",
    ]:

        valor = _importe_misma_linea(
            texto,
            etiqueta,
        )

        if valor is not None:
            return valor

    return None


def _detectar_total(
    texto: str,
) -> Optional[float]:

    for etiqueta in [
        r"Total\s+General\s*:",
        r"\bTotal\s*:",
    ]:

        valor = _importe_misma_linea(
            texto,
            etiqueta,
        )

        if valor is not None:
            return valor

    return None


def _detectar_iva(
    texto: str,
    neto: Optional[float],
    total: Optional[float],
) -> Optional[float]:
    """
    1) Busca "IVA: importe" en la misma línea.
    2) Si no es posible pero tenemos Neto y Total,
       calcula Total - Neto.

    Para facturas simples como la muestra:
        34.249.050 - 28.305.000 = 5.944.050
    """

    matches = re.findall(
        rf"\bIVA\s*:\s*{PATRON_IMPORTE}",
        texto,
        re.IGNORECASE,
    )

    if matches:

        # Usamos la última coincidencia porque en la cabecera
        # suele existir "IVA: IVA Resp. Inscripto", sin importe.
        valor = convertir_importe(
            matches[-1]
        )

        if valor is not None:
            return valor

    if neto is not None and total is not None:

        diferencia = round(
            total - neto,
            2,
        )

        if diferencia >= 0:
            return diferencia

    return None


# ============================================================
# CAE
# ============================================================

def _detectar_cae(
    texto: str,
) -> Optional[str]:

    return _buscar_primero(
        [
            r"Numero\s+de\s+CAE\s*:\s*(\d{14})",
            r"N[uú]mero\s+de\s+CAE\s*:\s*(\d{14})",
        ],
        texto,
    )


# ============================================================
# DETALLE
# ============================================================

def _detectar_detalle(
    texto: str,
) -> Optional[str]:

    patron = re.compile(
        r"^\s*(.+?)\s+"
        r"\d{1,3}(?:[.,]\d{3})?\s+"
        r"\d[\d\.,]*\s+"
        r"\d[\d\.,]*\s*$",
        re.MULTILINE,
    )

    for match in patron.finditer(texto):

        detalle = match.group(1).strip()

        if (
            "detalle" not in detalle.lower()
            and len(detalle) > 5
        ):
            return detalle

    return None


# ============================================================
# PARSER PRINCIPAL
# ============================================================

def parsear_factura(
    texto: str,
) -> Dict:

    tipo = _detectar_tipo_factura(
        texto
    )

    punto_venta, numero = (
        _detectar_numero_factura(
            texto
        )
    )

    fecha_factura = (
        _detectar_fecha_factura(
            texto
        )
    )

    vencimiento_cae = (
        _detectar_vencimiento_cae(
            texto
        )
    )

    cuit_cliente = (
        _detectar_cuit_cliente(
            texto
        )
    )

    cuit_proveedor = (
        _detectar_cuit_proveedor(
            texto,
            cuit_cliente,
        )
    )

    neto = _detectar_neto(
        texto
    )

    total = _detectar_total(
        texto
    )

    iva = _detectar_iva(
        texto,
        neto,
        total,
    )

    proveedor = (
        PROVEEDORES_POR_CUIT.get(
            cuit_proveedor
        )
        if cuit_proveedor
        else None
    )

    factura = {
        "fecha_factura": fecha_factura,
        "tipo": tipo,
        "punto_venta": punto_venta,
        "numero": numero,

        "proveedor": proveedor,
        "cuit_proveedor": cuit_proveedor,

        "cliente": _detectar_cliente(
            texto
        ),
        "cuit_cliente": cuit_cliente,

        "detalle": _detectar_detalle(
            texto
        ),

        "neto": neto,
        "iva": iva,
        "total": total,

        "cae": _detectar_cae(
            texto
        ),

        "vencimiento_cae": (
            vencimiento_cae
        ),
    }

    return factura


def crear_clave_factura(
    factura: Dict,
) -> Optional[str]:

    campos = [
        factura.get("cuit_proveedor"),
        factura.get("tipo"),
        factura.get("punto_venta"),
        factura.get("numero"),
    ]

    if not all(campos):
        return None

    return "-".join(
        str(campo).strip()
        for campo in campos
    )
