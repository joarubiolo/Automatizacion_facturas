"""
PARSER V5 - Facturas digitales + facturas escaneadas

Compatible con los formatos ya tratados:
- FACTURA A / A FACTURA
- Punto de Venta / Comp. Nro
- N° 0003 00000233
- Fecha / Fecha de Emisión
- ARCA
- facturas con Otros Tributos

Y agrega soporte para escaneos antiguos:
- "Factura N° 0004-00029837"
- "Fecha y Hora: 18/09/26 - 12:06:33"
- CUIT con espacios / guiones / errores menores
- "TOTAL"
- "PERCEPCIONES IVA"
- tablas OCR poco estructuradas

IMPORTANTE
----------
La detección por OCR nunca debe asumir que un CUIT es correcto
solo por tener 11 dígitos. Se valida su dígito verificador.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ============================================================
# PROVEEDORES CONOCIDOS
# ============================================================
# CAMBIAR / AGREGAR proveedores cuando lo desees.
#
# Esta tabla es útil cuando:
# - el nombre comercial está dentro de un logo;
# - el OCR lee mal el nombre;
# - el CUIT fue identificado correctamente.
#
PROVEEDORES_POR_CUIT = {
    "27329850027": "M.C Servicios",
    "20375558255": "ACHARES FRANCO EZEQUIEL",

    # Factura escaneada Diesel Motores.
    # El CUIT reconocido en la factura es válido según dígito verificador.
    "23175945709": "SANCHEZ PUERTA FEDERICO JOSE",
}


# ============================================================
# CUIT
# ============================================================

def normalizar_cuit(
    valor: Optional[str],
) -> Optional[str]:

    if not valor:
        return None

    digitos = re.sub(
        r"\D",
        "",
        str(valor),
    )

    if len(digitos) != 11:
        return None

    return digitos


def cuit_es_valido(
    cuit: Optional[str],
) -> bool:
    """
    Valida el dígito verificador del CUIT argentino.
    """

    cuit = normalizar_cuit(
        cuit
    )

    if not cuit:
        return False

    numeros = [
        int(x)
        for x in cuit
    ]

    pesos = [
        5, 4, 3, 2,
        7, 6, 5, 4,
        3, 2,
    ]

    suma = sum(
        numeros[i] * pesos[i]
        for i in range(10)
    )

    verificador = 11 - (
        suma % 11
    )

    if verificador == 11:
        verificador = 0

    elif verificador == 10:
        verificador = 9

    return (
        verificador
        == numeros[10]
    )


def _todos_los_cuits_validos(
    texto: str,
) -> List[str]:
    """
    Busca:
        20375558255
        20-37555825-5
        20 37555825 5
    """

    candidatos = re.findall(
        r"(?<!\d)"
        r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        r"(?!\d)",
        texto,
    )

    encontrados = []

    for candidato in candidatos:

        cuit = normalizar_cuit(
            candidato
        )

        if (
            cuit
            and cuit_es_valido(cuit)
            and cuit not in encontrados
        ):
            encontrados.append(
                cuit
            )

    return encontrados


# ============================================================
# UTILIDADES
# ============================================================

def _solo_original(
    texto: str,
) -> str:

    match = re.search(
        r"^\s*DUPLICADO\s*$",
        texto,
        re.IGNORECASE
        | re.MULTILINE,
    )

    if match:
        return texto[:match.start()]

    return texto


def convertir_importe(
    valor: Optional[str],
) -> Optional[float]:

    if not valor:
        return None

    valor = (
        str(valor)
        .strip()
        .replace("$", "")
        .replace(" ", "")
    )

    # Formato argentino:
    # 225.423,00
    if "," in valor:

        valor = valor.replace(
            ".",
            "",
        )

        valor = valor.replace(
            ",",
            ".",
        )

    # OCR puede devolver:
    # 225423.00
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
            re.IGNORECASE
            | re.MULTILINE,
        )

        if match:
            return (
                match
                .group(1)
                .strip()
            )

    return None


def _normalizar_fecha(
    fecha: Optional[str],
) -> Optional[str]:

    if not fecha:
        return None

    fecha = fecha.strip()

    for formato in (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
    ):

        try:
            valor = datetime.strptime(
                fecha,
                formato,
            )

            return valor.strftime(
                "%d/%m/%Y"
            )

        except ValueError:
            pass

    return None


# ============================================================
# TIPO
# ============================================================

def _detectar_tipo_factura(
    texto: str,
) -> Optional[str]:

    patrones = [
        r"\bFACTURA\s+([ABCEM])\b",
        r"\b([ABCEM])\s+FACTURA\b",
    ]

    tipo = _buscar_primero(
        patrones,
        texto,
    )

    if tipo:
        return tipo.upper()

    return None


# ============================================================
# NÚMERO DE FACTURA
# ============================================================

def _detectar_numero_factura(
    texto: str,
) -> Tuple[
    Optional[str],
    Optional[str],
]:

    patrones = [
        # ARCA moderno.
        (
            r"Punto\s+de\s+Venta\s*:\s*"
            r"(\d{4,5})"
            r"\s+Comp\.?\s*Nro\.?\s*:\s*"
            r"(\d{8})"
        ),

        # Formato tradicional.
        (
            r"N[°ºo.]?\s*"
            r"(\d{4,5})"
            r"\s*[- ]+\s*"
            r"(\d{8})"
        ),

        # Factura escaneada antigua.
        # Ej:
        # Factura N° 0004-00029837
        (
            r"Factura\s+N[°ºo.]?\s*"
            r"(\d{4,5})"
            r"\s*[- ]\s*"
            r"(\d{6,8})"
        ),

        # OCR suele leer "Nro".
        (
            r"Factura\s+(?:Nro|N°|Nº)\s*"
            r"(\d{4,5})"
            r"\s*[- ]\s*"
            r"(\d{6,8})"
        ),
    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE,
        )

        if match:

            punto_venta = (
                match.group(1)
            )

            numero = (
                match.group(2)
            )

            # Normalizamos a 8 dígitos.
            numero = numero.zfill(8)

            return (
                punto_venta,
                numero,
            )

    return None, None


# ============================================================
# FECHA
# ============================================================

def _detectar_fecha_factura(
    texto: str,
) -> Optional[str]:

    patrones = [
        (
            r"Fecha\s+de\s+Emisi[oó]n\s*:\s*"
            r"(\d{2}[/-]\d{2}[/-]\d{2,4})"
        ),

        (
            r"Fecha\s+y\s+Hora\s*:\s*"
            r"(\d{2}[/-]\d{2}[/-]\d{2,4})"
        ),

        (
            r"\bFecha\s*:\s*"
            r"(\d{2}[/-]\d{2}[/-]\d{2,4})"
        ),
    ]

    fecha = _buscar_primero(
        patrones,
        texto,
    )

    return _normalizar_fecha(
        fecha
    )


def _detectar_vencimiento_cae(
    texto: str,
) -> Optional[str]:

    fecha = _buscar_primero(
        [
            (
                r"Fecha\s+de\s+Vto\.?\s+de\s+CAE\s*:\s*"
                r"(\d{2}[/-]\d{2}[/-]\d{2,4})"
            ),

            (
                r"Fecha\s+Vencimiento\s+CAE\s*:\s*"
                r"(\d{2}[/-]\d{2}[/-]\d{2,4})"
            ),
        ],
        texto,
    )

    return _normalizar_fecha(
        fecha
    )


# ============================================================
# CUIT PROVEEDOR / CLIENTE
# ============================================================

def _detectar_cuit_cliente(
    texto: str,
) -> Optional[str]:

    # --------------------------------------------------------
    # INTENTO 1: contexto explícito
    # --------------------------------------------------------

    patrones = [
        (
            r"Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social"
            r".{0,220}?"
            r"CUIT\s*:?\s*"
            r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        ),

        (
            r"Sr\.?\s*:.*?"
            r"CUIT\s*:?\s*"
            r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        ),

        (
            r"Nombre\s+(?:Sr\.?|Sra\.?)"
            r".{0,220}?"
            r"CUIT\s*:?\s*"
            r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        ),
    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE
            | re.DOTALL,
        )

        if match:

            cuit = normalizar_cuit(
                match.group(1)
            )

            if cuit_es_valido(
                cuit
            ):
                return cuit

    # --------------------------------------------------------
    # INTENTO 2:
    # si existen dos CUIT válidos, el menos frecuente suele
    # corresponder al cliente.
    # --------------------------------------------------------

    todos = re.findall(
        r"(?<!\d)"
        r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        r"(?!\d)",
        texto,
    )

    validos = []

    for valor in todos:

        cuit = normalizar_cuit(
            valor
        )

        if cuit_es_valido(
            cuit
        ):
            validos.append(
                cuit
            )

    unicos = list(
        dict.fromkeys(validos)
    )

    if len(unicos) >= 2:

        conteo = Counter(
            validos
        )

        # El CUIT del cliente suele aparecer menos veces.
        return min(
            unicos,
            key=lambda c:
                conteo[c],
        )

    return None


def _detectar_cuit_proveedor(
    texto: str,
    cuit_cliente: Optional[str],
) -> Optional[str]:

    candidatos = []

    encontrados = re.findall(
        r"(?<!\d)"
        r"(\d{2}[-\s]?\d{8}[-\s]?\d)"
        r"(?!\d)",
        texto,
    )

    for valor in encontrados:

        cuit = normalizar_cuit(
            valor
        )

        if not cuit:
            continue

        if not cuit_es_valido(
            cuit
        ):
            continue

        if cuit == cuit_cliente:
            continue

        candidatos.append(
            cuit
        )

    if not candidatos:
        return None

    return (
        Counter(candidatos)
        .most_common(1)[0][0]
    )


# ============================================================
# NOMBRES
# ============================================================

def _detectar_proveedor(
    texto: str,
    cuit_proveedor: Optional[str],
) -> Optional[str]:

    # Primero usamos CUIT -> nombre.
    if cuit_proveedor:

        conocido = (
            PROVEEDORES_POR_CUIT
            .get(cuit_proveedor)
        )

        if conocido:
            return conocido

    # Facturas ARCA.
    match = re.search(
        r"^\s*Raz[oó]n\s+Social\s*:\s*"
        r"(.+?)"
        r"(?=\s{2,}(?:Fecha|CUIT|Domicilio|Condici[oó]n)|$)",
        texto,
        re.IGNORECASE
        | re.MULTILINE,
    )

    if match:
        return " ".join(
            match.group(1).split()
        )

    return None


def _detectar_cliente(
    texto: str,
) -> Optional[str]:

    patrones = [
        (
            r"Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}(?:Domicilio|Condici[oó]n|CUIT)|$)"
        ),

        (
            r"^\s*Sr\.?\s*:\s*"
            r"(.+?)"
            r"(?=\s{2,}CUIT\s*:|$)"
        ),

        # Formato escaneado:
        # Nombre Sr.
        # KARPA SA
        (
            r"Nombre\s+(?:Sr\.?|Sra\.?)\s*:?\s*\n"
            r"\s*(.+?)\s*$"
        ),
    ]

    for patron in patrones:

        match = re.search(
            patron,
            texto,
            re.IGNORECASE
            | re.MULTILINE,
        )

        if match:

            valor = " ".join(
                match.group(1).split()
            )

            if (
                valor
                and len(valor) <= 120
            ):
                return valor

    return None


# ============================================================
# IMPORTES
# ============================================================

PATRON_IMPORTE = (
    r"([0-9]+(?:\.[0-9]{3})*(?:,[0-9]{2})"
    r"|[0-9]+(?:,[0-9]{2})"
    r"|[0-9]+\.[0-9]{2})"
)


def _buscar_importe(
    texto: str,
    patrones: List[str],
) -> Optional[float]:

    for etiqueta in patrones:

        match = re.search(
            rf"{etiqueta}"
            rf"[^\r\n0-9]*"
            rf"{PATRON_IMPORTE}",
            texto,
            re.IGNORECASE,
        )

        if match:
            valor = convertir_importe(
                match.group(1)
            )

            if valor is not None:
                return valor

    return None


def _detectar_neto(
    texto: str,
) -> Optional[float]:

    return _buscar_importe(
        texto,
        [
            r"Importe\s+Neto\s+Gravado\s*:\s*",
            r"Sub[- ]?Total\s*[:=]*\s*",
            r"Neto\s+Gravado\s*:\s*",
        ],
    )


def _detectar_importe_otros_tributos(
    texto: str,
) -> float:

    valor = _buscar_importe(
        texto,
        [
            r"Importe\s+Otros\s+Tributos\s*:\s*",
            r"Percepciones\s+Otros\s*[:=]*\s*",
        ],
    )

    return float(
        valor or 0.0
    )


def _detectar_total(
    texto: str,
) -> Optional[float]:

    return _buscar_importe(
        texto,
        [
            r"Importe\s+Total\s*:\s*",
            r"Total\s+General\s*:\s*",
            r"\bTOTAL\s*[:=]*\s*\$?\s*",
        ],
    )


def _detectar_iva(
    texto: str,
    neto: Optional[float],
    total: Optional[float],
    otros_tributos: float,
) -> Optional[float]:

    # Facturas ARCA con distintas alícuotas.
    importes = re.findall(
        rf"\bIVA\s+\d+(?:[\.,]\d+)?%"
        rf"\s*:\s*\$?\s*"
        rf"{PATRON_IMPORTE}",
        texto,
        re.IGNORECASE,
    )

    valores = [
        convertir_importe(x)
        for x in importes
    ]

    valores = [
        x
        for x in valores
        if x is not None
    ]

    if valores:
        return round(
            sum(valores),
            2,
        )

    # Factura simple.
    iva_simple = _buscar_importe(
        texto,
        [
            r"^\s*IVA\s*:\s*",
            r"^\s*Iva\s*:\s*",
        ],
    )

    if iva_simple is not None:
        return iva_simple

    # Facturas antiguas:
    # SUBTOTAL | ALICUOTA IVA | IVA | PERCEPCIONES IVA
    #
    # Buscamos un IVA cercano al bloque inferior.
    match = re.search(
        rf"(?:ALICUOTA\s+IVA|AL[IÍ]CUOTA\s+IVA)"
        rf".{{0,180}}?"
        rf"{PATRON_IMPORTE}",
        texto,
        re.IGNORECASE
        | re.DOTALL,
    )

    if match:
        valor = convertir_importe(
            match.group(1)
        )

        if valor is not None:
            return valor

    # Último recurso: cálculo aritmético.
    if (
        neto is not None
        and total is not None
    ):

        calculado = round(
            total
            - neto
            - otros_tributos,
            2,
        )

        if calculado >= 0:
            return calculado

    return None


# ============================================================
# CAE
# ============================================================

def _detectar_cae(
    texto: str,
) -> Optional[str]:

    return _buscar_primero(
        [
            r"CAE\s+N[°ºo.]?\s*:\s*(\d{14})",
            r"N[uú]mero\s+de\s+CAE\s*:\s*(\d{14})",
            r"Numero\s+de\s+CAE\s*:\s*(\d{14})",
        ],
        texto,
    )


# ============================================================
# DETALLE
# ============================================================

def _detectar_detalle(
    texto: str,
) -> Optional[str]:

    detalles: List[str] = []

    # Formato digital ARCA.
    patron_arca = re.compile(
        r"^\s*\d+\s+"
        r"(.+?)"
        r"\s+\d+,\d+\s+"
        r"(?:unidades?|unidad|u\.?|kg|lts?|litros?|servicios?)\b",
        re.IGNORECASE
        | re.MULTILINE,
    )

    for match in patron_arca.finditer(
        texto
    ):

        descripcion = " ".join(
            match.group(1).split()
        )

        if descripcion:
            detalles.append(
                descripcion
            )

    # Formato escaneado antiguo.
    # Cantidad + código/descripción + precio.
    patron_scan = re.compile(
        r"^\s*"
        r"\d+[,.]\d+\s+"
        r"(.{5,100}?)"
        r"\s+\d[\d\.,]*"
        r"(?:\s+\(?\d{1,2}[,.]\d{2}\)?)?",
        re.MULTILINE,
    )

    for match in patron_scan.finditer(
        texto
    ):

        descripcion = " ".join(
            match.group(1).split()
        )

        if (
            descripcion
            and descripcion not in detalles
        ):
            detalles.append(
                descripcion
            )

    # Formato M.C Servicios.
    patron_generico = re.compile(
        r"^\s*(.+?)\s+"
        r"\d{1,3}(?:[.,]\d{3})?\s+"
        r"\d[\d\.,]*\s+"
        r"\d[\d\.,]*\s*$",
        re.MULTILINE,
    )

    for match in patron_generico.finditer(
        texto
    ):

        descripcion = " ".join(
            match.group(1).split()
        )

        if (
            descripcion
            and "detalle" not in descripcion.lower()
            and len(descripcion) > 5
            and descripcion not in detalles
        ):
            detalles.append(
                descripcion
            )

    if not detalles:
        return None

    # Evita textos muy largos o basura OCR.
    detalles = [
        x
        for x in detalles
        if len(x) <= 180
    ]

    return " | ".join(
        detalles[:10]
    )


# ============================================================
# PARSER PRINCIPAL
# ============================================================

def parsear_factura(
    texto: str,
) -> Dict:

    texto = _solo_original(
        texto
    )

    tipo = _detectar_tipo_factura(
        texto
    )

    punto_venta, numero = (
        _detectar_numero_factura(
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

    otros_tributos = (
        _detectar_importe_otros_tributos(
            texto
        )
    )

    iva = _detectar_iva(
        texto,
        neto,
        total,
        otros_tributos,
    )

    return {
        "fecha_factura":
            _detectar_fecha_factura(
                texto
            ),

        "tipo":
            tipo,

        "punto_venta":
            punto_venta,

        "numero":
            numero,

        "proveedor":
            _detectar_proveedor(
                texto,
                cuit_proveedor,
            ),

        "cuit_proveedor":
            cuit_proveedor,

        "cliente":
            _detectar_cliente(
                texto
            ),

        "cuit_cliente":
            cuit_cliente,

        "detalle":
            _detectar_detalle(
                texto
            ),

        "neto":
            neto,

        "iva":
            iva,

        "importe_otros_tributos":
            otros_tributos,

        "total":
            total,

        "cae":
            _detectar_cae(
                texto
            ),

        "vencimiento_cae":
            _detectar_vencimiento_cae(
                texto
            ),
    }


def crear_clave_factura(
    factura: Dict,
) -> Optional[str]:

    campos = [
        factura.get(
            "cuit_proveedor"
        ),
        factura.get(
            "tipo"
        ),
        factura.get(
            "punto_venta"
        ),
        factura.get(
            "numero"
        ),
    ]

    if not all(campos):
        return None

    return "-".join(
        str(campo).strip()
        for campo in campos
    )
