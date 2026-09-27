"""
Extractor de texto para facturas.

CAMBIO IMPORTANTE V2:
Para PDFs digitales usamos sort=True en PyMuPDF.
Esto ordena el texto por posición visual y evita que:
- un código postal se confunda con el punto de venta,
- un CUIT se asocie a la persona incorrecta,
- los importes de IVA/Subtotal se mezclen.

Para PDFs escaneados o imágenes se mantiene Tesseract OCR.
"""

from __future__ import annotations

import io
from typing import Tuple

import pymupdf
import pytesseract
from PIL import Image

from config import MIN_TEXT_LENGTH, TESSERACT_CMD, TESSERACT_LANG


# CAMBIAR en config.py si Tesseract está instalado en otra ruta.
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _normalizar_texto(texto: str) -> str:
    """
    Conserva los saltos de línea porque ayudan al parser,
    pero elimina espacios innecesarios al inicio/final de cada línea.

    IMPORTANTE:
    No usamos " ".join(texto.split()) porque perderíamos
    la estructura visual de la factura.
    """
    lineas = []

    for linea in texto.splitlines():
        # Conservamos los espacios internos.
        limpia = linea.rstrip()

        if limpia.strip():
            lineas.append(limpia)

    return "\n".join(lineas)


def extraer_texto_pdf(archivo: io.BytesIO) -> Tuple[str, str]:
    """
    Devuelve:
        texto
        metodo: "PDF_TEXTO" u "OCR"
    """
    contenido = archivo.getvalue()

    documento = pymupdf.open(
        stream=contenido,
        filetype="pdf",
    )

    texto_digital = []

    for pagina in documento:
        # CAMBIO CLAVE:
        # sort=True ordena los elementos según su posición visual.
        texto_digital.append(
            pagina.get_text("text", sort=True)
        )

    texto = _normalizar_texto(
        "\n".join(texto_digital)
    )

    if len(texto.strip()) >= MIN_TEXT_LENGTH:
        return texto, "PDF_TEXTO"

    # --------------------------------------------------------
    # FALLBACK OCR
    # --------------------------------------------------------
    paginas_ocr = []

    for pagina in documento:
        pix = pagina.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            alpha=False,
        )

        imagen = Image.open(
            io.BytesIO(pix.tobytes("png"))
        )

        texto_pagina = pytesseract.image_to_string(
            imagen,
            lang=TESSERACT_LANG,
        )

        paginas_ocr.append(texto_pagina)

    texto_ocr = _normalizar_texto(
        "\n".join(paginas_ocr)
    )

    return texto_ocr, "OCR"


def extraer_texto_imagen(
    archivo: io.BytesIO,
) -> Tuple[str, str]:
    """
    OCR para JPG, JPEG y PNG.
    """
    archivo.seek(0)

    imagen = Image.open(archivo)

    texto = pytesseract.image_to_string(
        imagen,
        lang=TESSERACT_LANG,
    )

    return _normalizar_texto(texto), "OCR"


def extraer_texto(
    archivo: io.BytesIO,
    mime_type: str,
    nombre_archivo: str = "",
) -> Tuple[str, str]:
    """
    Punto de entrada principal.
    """
    mime_type = (mime_type or "").lower()

    extension = (
        nombre_archivo.lower().split(".")[-1]
        if "." in nombre_archivo
        else ""
    )

    if mime_type == "application/pdf" or extension == "pdf":
        return extraer_texto_pdf(archivo)

    if (
        mime_type.startswith("image/")
        or extension in {"jpg", "jpeg", "png"}
    ):
        return extraer_texto_imagen(archivo)

    raise ValueError(
        f"Formato no soportado: {mime_type or extension}. "
        "Usá PDF, JPG, JPEG o PNG."
    )
