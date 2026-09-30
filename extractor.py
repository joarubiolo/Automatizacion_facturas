"""
EXTRACTOR V5 - PDF digital + OCR mejorado para facturas escaneadas

OBJETIVO
--------
1) Si el PDF contiene texto digital suficiente:
      PyMuPDF -> texto ordenado con sort=True.
2) Si es un escaneo / CamScanner / imagen:
      - render a mayor resolución
      - escala de grises
      - autocontraste
      - aumento de contraste
      - enfoque
      - binarización suave
      - OCR global
      - OCR por regiones (cabecera / cuerpo / pie)
3) Se devuelve texto para el parser sin cambiar la interfaz del proyecto:
      texto, metodo = extraer_texto(...)

NO requiere nuevas librerías.
Usa únicamente:
    PyMuPDF
    Pillow
    pytesseract

IMPORTANTE
----------
Este archivo es compatible con tu app.py actual.
"""

from __future__ import annotations

import io
from typing import Tuple, List

import pymupdf
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

import config


# ============================================================
# CONFIGURACIÓN
# ============================================================

TESSERACT_CMD = getattr(
    config,
    "TESSERACT_CMD",
    "tesseract",
)

TESSERACT_LANG = getattr(
    config,
    "TESSERACT_LANG",
    "spa",
)

MIN_TEXT_LENGTH = int(
    getattr(
        config,
        "MIN_TEXT_LENGTH",
        100,
    )
)

# CAMBIAR opcionalmente en config.py.
# 3 = buena calidad para facturas escaneadas.
OCR_SCALE = float(
    getattr(
        config,
        "OCR_SCALE",
        3.0,
    )
)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# ============================================================
# UTILIDADES
# ============================================================

def _normalizar_texto(texto: str) -> str:
    """
    Conserva saltos de línea.
    Elimina únicamente líneas completamente vacías repetidas
    y espacios finales.
    """
    resultado: List[str] = []

    for linea in texto.splitlines():
        limpia = linea.rstrip()

        if limpia.strip():
            resultado.append(limpia)

    return "\n".join(resultado)


def _preprocesar_imagen(imagen: Image.Image) -> Image.Image:
    """
    Preprocesamiento conservador pensado para:
    - CamScanner
    - tickets / facturas antiguas
    - impresiones con bajo contraste
    - texto gris sobre fondo blanco

    No usamos OpenCV para mantener el proyecto ligero.
    """

    # Escala de grises.
    imagen = imagen.convert("L")

    # Mejora contraste global.
    imagen = ImageOps.autocontrast(
        imagen,
        cutoff=1,
    )

    # Aumenta contraste.
    imagen = ImageEnhance.Contrast(
        imagen
    ).enhance(1.8)

    # Aumenta ligeramente nitidez.
    imagen = ImageEnhance.Sharpness(
        imagen
    ).enhance(1.5)

    # Filtro final de enfoque.
    imagen = imagen.filter(
        ImageFilter.SHARPEN
    )

    return imagen


def _ocr(
    imagen: Image.Image,
    psm: int = 6,
) -> str:
    """
    Ejecuta Tesseract con una configuración apropiada
    para documentos.
    """
    config_tesseract = (
        f"--oem 3 --psm {psm} "
        "-c preserve_interword_spaces=1"
    )

    return pytesseract.image_to_string(
        imagen,
        lang=TESSERACT_LANG,
        config=config_tesseract,
    )


def _recortar_porcentaje(
    imagen: Image.Image,
    y0: float,
    y1: float,
) -> Image.Image:
    """
    Recorta una zona vertical utilizando porcentajes.
    """
    ancho, alto = imagen.size

    return imagen.crop(
        (
            0,
            int(alto * y0),
            ancho,
            int(alto * y1),
        )
    )


def _ocr_documento_escaneado(
    imagen: Image.Image,
) -> str:
    """
    OCR híbrido:
    - página completa
    - cabecera
    - cuerpo
    - pie

    Los OCR por regiones ayudan especialmente con:
    CUIT, fecha, número de factura, subtotal, IVA y total.
    """

    procesada = _preprocesar_imagen(
        imagen
    )

    bloques = []

    # --------------------------------------------------------
    # 1. OCR GLOBAL
    # --------------------------------------------------------
    global_psm6 = _ocr(
        procesada,
        psm=6,
    )

    bloques.append(
        "=== OCR_GLOBAL ===\n"
        + global_psm6
    )

    # PSM 11 funciona mejor cuando el documento tiene
    # texto disperso en diferentes zonas.
    global_psm11 = _ocr(
        procesada,
        psm=11,
    )

    bloques.append(
        "=== OCR_GLOBAL_DISPERSO ===\n"
        + global_psm11
    )

    # --------------------------------------------------------
    # 2. OCR POR REGIONES
    # --------------------------------------------------------

    # Cabecera:
    # proveedor, tipo, número, fecha, CUIT.
    cabecera = _recortar_porcentaje(
        procesada,
        0.00,
        0.36,
    )

    bloques.append(
        "=== OCR_CABECERA ===\n"
        + _ocr(cabecera, psm=6)
    )

    # Cuerpo:
    # cliente y productos.
    cuerpo = _recortar_porcentaje(
        procesada,
        0.25,
        0.72,
    )

    bloques.append(
        "=== OCR_CUERPO ===\n"
        + _ocr(cuerpo, psm=6)
    )

    # Pie:
    # subtotal, IVA, percepciones, total, CAE / CAI.
    pie = _recortar_porcentaje(
        procesada,
        0.62,
        1.00,
    )

    bloques.append(
        "=== OCR_PIE ===\n"
        + _ocr(pie, psm=6)
    )

    return _normalizar_texto(
        "\n".join(bloques)
    )


# ============================================================
# PDF
# ============================================================

def extraer_texto_pdf(
    archivo: io.BytesIO,
) -> Tuple[str, str]:

    contenido = archivo.getvalue()

    documento = pymupdf.open(
        stream=contenido,
        filetype="pdf",
    )

    # --------------------------------------------------------
    # INTENTO 1: TEXTO DIGITAL
    # --------------------------------------------------------
    paginas_texto = []

    for pagina in documento:

        # sort=True es fundamental para facturas digitales.
        paginas_texto.append(
            pagina.get_text(
                "text",
                sort=True,
            )
        )

    texto_digital = _normalizar_texto(
        "\n".join(paginas_texto)
    )

    if len(texto_digital.strip()) >= MIN_TEXT_LENGTH:
        return (
            texto_digital,
            "PDF_TEXTO",
        )

    # --------------------------------------------------------
    # INTENTO 2: OCR
    # --------------------------------------------------------
    paginas_ocr = []

    for numero_pagina, pagina in enumerate(
        documento,
        start=1,
    ):

        pix = pagina.get_pixmap(
            matrix=pymupdf.Matrix(
                OCR_SCALE,
                OCR_SCALE,
            ),
            alpha=False,
        )

        imagen = Image.open(
            io.BytesIO(
                pix.tobytes("png")
            )
        )

        texto_pagina = (
            _ocr_documento_escaneado(
                imagen
            )
        )

        paginas_ocr.append(
            f"=== PAGINA {numero_pagina} ===\n"
            + texto_pagina
        )

    return (
        _normalizar_texto(
            "\n".join(paginas_ocr)
        ),
        "OCR_MEJORADO",
    )


# ============================================================
# IMÁGENES
# ============================================================

def extraer_texto_imagen(
    archivo: io.BytesIO,
) -> Tuple[str, str]:

    archivo.seek(0)

    imagen = Image.open(
        archivo
    )

    texto = _ocr_documento_escaneado(
        imagen
    )

    return (
        texto,
        "OCR_MEJORADO",
    )


# ============================================================
# FUNCIÓN PRINCIPAL
# ============================================================

def extraer_texto(
    archivo: io.BytesIO,
    mime_type: str,
    nombre_archivo: str = "",
) -> Tuple[str, str]:

    mime_type = (
        mime_type or ""
    ).lower()

    extension = (
        nombre_archivo
        .lower()
        .split(".")[-1]
        if "." in nombre_archivo
        else ""
    )

    if (
        mime_type == "application/pdf"
        or extension == "pdf"
    ):
        return extraer_texto_pdf(
            archivo
        )

    if (
        mime_type.startswith("image/")
        or extension in {
            "jpg",
            "jpeg",
            "png",
        }
    ):
        return extraer_texto_imagen(
            archivo
        )

    raise ValueError(
        "Formato no soportado: "
        f"{mime_type or extension}. "
        "Usá PDF, JPG, JPEG o PNG."
    )
