"""
PARSER V3 - Facturas argentinas

Mejoras:
- Soporta "FACTURA A" y "A FACTURA".
- Soporta puntos de venta de 4 o 5 dígitos.
- Soporta "Fecha:" y "Fecha de Emisión:".
- Distingue CUIT del proveedor y del cliente.
- Detecta Razón Social del proveedor y cliente.
- Detecta CAE y vencimiento con distintas etiquetas.
- Suma correctamente IVA por alícuotas (21%, 10.5%, etc.).
- Detecta "Importe Otros Tributos" como campo independiente.
- Extrae varios productos/servicios en el campo detalle.
- Si el PDF trae ORIGINAL + DUPLICADO + TRIPLICADO, analiza solamente ORIGINAL.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional


# ============================================================
# PROVEEDORES CONOCIDOS (OPCIONAL)
# ============================================================
# Útil cuando la razón social está solamente dentro de un logo
# y no forma parte del texto digital del PDF.
#
# CAMBIAR / AGREGAR proveedores si lo necesitás.
#
PROVEEDORES_POR_CUIT = {
    "27329850027": "M.C Servicios",
    # "20123456789": "Otro proveedor",
}


def _solo_original(texto: str) -> str:
    """
    Algunos comprobantes contienen ORIGINAL, DUPLICADO y TRIPLICADO
    como páginas separadas. Si detectamos DUPLICADO, nos quedamos
    únicamente con el bloque anterior para no procesar todo 3 veces.
    """
    match = re.search(
        r"^\s*DUPLICADO\s*$",
        texto,
        re.IGNORECASE | re.MULTILINE,
    )

    if match:
        return texto[:match.start()]

    return texto


def convertir_importe(valor: Optional[str]) -> Optional[float]:
    """
    Convierte importes argentinos:
        1.596.000,00 -> 1596000.00
        1596000,00   -> 1596000.00
    """
    if not valor:
        return None

    valor = (
        str(valor)
        .strip()
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

def _detectar_tipo_factura(texto: str) -> Optional[str]:
    patrones = [
        # Ej.: FACTURA A
        r"\bFACTURA\s+([ABCEM])\b",

        # Ej.: A FACTURA
        r"\b([ABCEM])\s+FACTURA\b",
    ]

    tipo = _buscar_primero(patrones, texto)

    return tipo.upper() if tipo else None


# ============================================================
# PUNTO DE VENTA Y NÚMERO
# ============================================================

def _detectar_numero_factura(texto: str):
    patrones = [
        # Formato ARCA:
        # Punto de Venta: 00002 Comp. Nro: 00003746
        (
            r"Punto\s+de\s+Venta\s*:\s*(\d{4,5})"
            r"\s+Comp\.?\s*Nro\.?\s*:\s*(\d{8})"
        ),

        # Formato:
        # N° 0003 00000233
        (
            r"N[°ºo.]?\s*"
            r"(\d{4,5})"
            r"\s*[- ]+\s*"
            r"(\d{8})"
        ),
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE,
        )

        if match:
            return match.group(1), match.group(2)

    return None, None


# ============================================================
# FECHAS
# ============================================================

def _detectar_fecha_factura(texto: str) -> Optional[str]:
    return _buscar_primero(
        [
            r"Fecha\s+de\s+Emisi[oó]n\s*:\s*(\d{2}/\d{2}/\d{4})",
            r"\bFecha\s*:\s*(\d{2}/\d{2}/\d{4})",
        ],
        texto,
    )


def _detectar_vencimiento_cae(texto: str) -> Optional[str]:
    return _buscar_primero(
        [
            r"Fecha\s+de\s+Vto\.?\s+de\s+CAE\s*:\s*(\d{2}/\d{2}/\d{4})",
            r"Fecha\s+Vencimiento\s+CAE\s*:\s*(\d{2}/\d{2}/\d{4})",
        ],
        texto,
    )


# ============================================================
# CLIENTE
# ============================================================

def _detectar_cliente(texto: str) -> Optional[str]:
    patrones = [
        # ARCA:
        # Apellido y Nombre / Razón Social: KARPA SA
        (
            r"Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}(?:Domicilio|Condici[oó]n|CUIT)|$)"
        ),

        # Otros formatos:
        (
            r"^\s*Sr\.?\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|$)"
        ),

        (
            r"^\s*Cliente\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|$)"
        ),
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE | re.MULTILINE,
        )

        if match:
            valor = " ".join(match.group(1).split())

            if valor:
                return valor

    return None


def _detectar_cuit_cliente(texto: str) -> Optional[str]:
    patrones = [
        # ARCA sorted text:
        # CUIT: 30561286686     Apellido y Nombre / Razón Social: KARPA SA
        (
            r"^\s*CUIT\s*:?\s*(\d{11})"
            r".{0,160}?"
            r"Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social"
        ),

        # Formato viejo:
        # Sr: KARPA SA      CUIT: 30561286686
        (
            r"^\s*Sr\.?\s*:.*?"
            r"\bCUIT\s*:?\s*(\d{11})"
        ),

        (
            r"^\s*Cliente\s*:.*?"
            r"\bCUIT\s*:?\s*(\d{11})"
        ),
    ]

    for patron in patrones:
        match = re.search(
            patron,
            texto,
            re.IGNORECASE | re.MULTILINE,
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# PROVEEDOR
# ============================================================

def _detectar_proveedor(texto: str) -> Optional[str]:
    """
    Detecta la razón social del emisor.

    IMPORTANTE:
    Se exige que "Razón Social:" esté al inicio lógico de una línea
    para no confundirla con:
    "Apellido y Nombre / Razón Social:" del cliente.
    """
    match = re.search(
        r"^\s*Raz[oó]n\s+Social\s*:\s*"
        r"(.+?)"
        r"(?=\s{2,}(?:Fecha|CUIT|Domicilio|Condici[oó]n)|$)",
        texto,
        re.IGNORECASE | re.MULTILINE,
    )

    if not match:
        return None

    return " ".join(match.group(1).split())


def _todos_los_cuits(texto: str) -> List[str]:
    return re.findall(
        r"(?<!\d)(\d{11})(?!\d)",
        texto,
    )


def _detectar_cuit_proveedor(
    texto: str,
    cuit_cliente: Optional[str],
) -> Optional[str]:
    """
    El CUIT del emisor suele repetirse en la cabecera
    (CUIT + Ingresos Brutos), por eso usamos el candidato
    más frecuente excluyendo el CUIT del cliente.
    """
    candidatos = [
        cuit
        for cuit in _todos_los_cuits(texto)
        if cuit != cuit_cliente
    ]

    if not candidatos:
        return None

    return Counter(candidatos).most_common(1)[0][0]


# ============================================================
# IMPORTES
# ============================================================

PATRON_IMPORTE = (
    r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}"
    r"|[0-9]+,[0-9]{2})"
)


def _buscar_importe(texto: str, patrones: List[str]) -> Optional[float]:
    for etiqueta in patrones:
        match = re.search(
            rf"{etiqueta}\s*\$?\s*{PATRON_IMPORTE}",
            texto,
            re.IGNORECASE,
        )

        if match:
            return convertir_importe(match.group(1))

    return None


def _detectar_neto(texto: str) -> Optional[float]:
    return _buscar_importe(
        texto,
        [
            r"Importe\s+Neto\s+Gravado\s*:\s*",
            r"Sub[- ]?Total\s*:\s*",
            r"Neto\s+Gravado\s*:\s*",
        ],
    )


def _detectar_importe_otros_tributos(texto: str) -> float:
    """
    Devuelve 0 si no existen otros tributos.

    Se toma la primera línea resumen:
        Importe Otros Tributos: $ 144000,00

    NO se suman repeticiones del mismo importe.
    """
    valor = _buscar_importe(
        texto,
        [
            r"Importe\s+Otros\s+Tributos\s*:\s*",
        ],
    )

    return float(valor or 0.0)


def _detectar_iva(
    texto: str,
    neto: Optional[float],
    total: Optional[float],
    importe_otros_tributos: float,
) -> Optional[float]:
    """
    Prioridad 1:
    suma las líneas resumen por alícuota:
        IVA 21%: $ 252000,00
        IVA 10.5%: $ 0,00

    Prioridad 2:
    busca un IVA simple:
        Iva: 5944050,00

    Prioridad 3:
    calcula:
        total - neto - otros_tributos
    """

    importes_iva = re.findall(
        rf"\bIVA\s+\d+(?:[\.,]\d+)?%\s*:\s*\$?\s*{PATRON_IMPORTE}",
        texto,
        re.IGNORECASE,
    )

    if importes_iva:
        valores = [
            convertir_importe(valor)
            for valor in importes_iva
        ]

        valores = [
            valor
            for valor in valores
            if valor is not None
        ]

        if valores:
            return round(sum(valores), 2)

    # Formato simple: "Iva: 5944050,00"
    match = re.search(
        rf"^\s*IVA\s*:\s*\$?\s*{PATRON_IMPORTE}",
        texto,
        re.IGNORECASE | re.MULTILINE,
    )

    if match:
        valor = convertir_importe(match.group(1))

        if valor is not None:
            return valor

    # Último recurso.
    if neto is not None and total is not None:
        calculado = round(
            total - neto - importe_otros_tributos,
            2,
        )

        if calculado >= 0:
            return calculado

    return None


def _detectar_total(texto: str) -> Optional[float]:
    return _buscar_importe(
        texto,
        [
            r"Importe\s+Total\s*:\s*",
            r"Total\s+General\s*:\s*",
            r"\bTotal\s*:\s*",
        ],
    )


# ============================================================
# CAE
# ============================================================

def _detectar_cae(texto: str) -> Optional[str]:
    return _buscar_primero(
        [
            r"CAE\s+N[°ºo.]?\s*:\s*(\d{14})",
            r"N[uú]mero\s+de\s+CAE\s*:\s*(\d{14})",
            r"Numero\s+de\s+CAE\s*:\s*(\d{14})",
        ],
        texto,
    )


# ============================================================
# DETALLE / PRODUCTOS
# ============================================================

def _detectar_detalles_arca(texto: str) -> List[str]:
    """
    Extrae descripciones del formato de tabla ARCA.

    Ejemplo:
        0 PARANTE DELANTERO ... 1,00 unidades ...
          0006788065)-

        0 FRENTE ... 1,00 unidades ...
    """

    if "Producto / Servicio" not in texto:
        return []

    # Nos quedamos con la zona de productos.
    inicio = texto.find("Producto / Servicio")

    fin_candidates = [
        pos
        for pos in [
            texto.find("Otros Tributos", inicio),
            texto.find("Importe Neto Gravado", inicio),
        ]
        if pos != -1
    ]

    fin = min(fin_candidates) if fin_candidates else len(texto)

    seccion = texto[inicio:fin]
    lineas = seccion.splitlines()

    detalles: List[str] = []
    actual: Optional[int] = None

    patron_fila = re.compile(
        r"^\s*\d+\s+"
        r"(.+?)"
        r"\s+\d+,\d+\s+"
        r"(?:unidades?|unidad|u\.?|kg|lts?|litros?|servicios?)\b",
        re.IGNORECASE,
    )

    for linea in lineas:
        limpia = linea.strip()

        if not limpia:
            continue

        # Ignorar encabezados.
        if any(
            palabra in limpia.lower()
            for palabra in [
                "producto / servicio",
                "código",
                "precio unit",
                "subtotal c/iva",
                "alicuota",
            ]
        ):
            continue

        match = patron_fila.search(linea)

        if match:
            descripcion = " ".join(
                match.group(1).split()
            )

            detalles.append(descripcion)
            actual = len(detalles) - 1
            continue

        # Línea de continuación de una descripción, por ejemplo:
        # "0006788065)-"
        if actual is not None:
            if not re.search(
                r"\d+,\d{2}.*\d+,\d{2}",
                limpia,
            ):
                detalles[actual] = (
                    detalles[actual]
                    + " "
                    + " ".join(limpia.split())
                ).strip()

    # Elimina repetidos conservando orden.
    unicos = []

    for detalle in detalles:
        if detalle not in unicos:
            unicos.append(detalle)

    return unicos


def _detectar_detalle_generico(texto: str) -> Optional[str]:
    """
    Fallback para formatos antiguos.
    """
    patron = re.compile(
        r"^\s*(.+?)\s+"
        r"\d{1,3}(?:[.,]\d{3})?\s+"
        r"\d[\d\.,]*\s+"
        r"\d[\d\.,]*\s*$",
        re.MULTILINE,
    )

    for match in patron.finditer(texto):
        detalle = " ".join(
            match.group(1).split()
        )

        if (
            "detalle" not in detalle.lower()
            and len(detalle) > 5
        ):
            return detalle

    return None


def _detectar_detalle(texto: str) -> Optional[str]:
    detalles = _detectar_detalles_arca(texto)

    if detalles:
        return " | ".join(detalles)

    return _detectar_detalle_generico(texto)


# ============================================================
# PARSER PRINCIPAL
# ============================================================

def parsear_factura(texto: str) -> Dict:
    # Evita analizar DUPLICADO / TRIPLICADO.
    texto = _solo_original(texto)

    tipo = _detectar_tipo_factura(texto)
    punto_venta, numero = _detectar_numero_factura(texto)

    cuit_cliente = _detectar_cuit_cliente(texto)

    cuit_proveedor = _detectar_cuit_proveedor(
        texto,
        cuit_cliente,
    )

    proveedor = _detectar_proveedor(texto)

    # Si el nombre no está en texto (por ejemplo está en un logo),
    # usamos el CUIT como clave de respaldo.
    if not proveedor and cuit_proveedor:
        proveedor = PROVEEDORES_POR_CUIT.get(
            cuit_proveedor
        )

    neto = _detectar_neto(texto)
    total = _detectar_total(texto)
    importe_otros_tributos = _detectar_importe_otros_tributos(texto)

    iva = _detectar_iva(
        texto,
        neto,
        total,
        importe_otros_tributos,
    )

    return {
        "fecha_factura": _detectar_fecha_factura(texto),
        "tipo": tipo,
        "punto_venta": punto_venta,
        "numero": numero,

        "proveedor": proveedor,
        "cuit_proveedor": cuit_proveedor,

        "cliente": _detectar_cliente(texto),
        "cuit_cliente": cuit_cliente,

        "detalle": _detectar_detalle(texto),

        "neto": neto,
        "iva": iva,
        "total": total,

        # Este campo se usa internamente para validar la ecuación.
        # google_services.py puede ignorarlo: no hace falta agregar
        # una columna al Sheet si no querés.
        "importe_otros_tributos": importe_otros_tributos,

        "cae": _detectar_cae(texto),
        "vencimiento_cae": _detectar_vencimiento_cae(texto),
    }


def crear_clave_factura(factura: Dict) -> Optional[str]:
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
