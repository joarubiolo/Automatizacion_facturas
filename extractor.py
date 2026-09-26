"""
Extracción de texto desde PDF, JPG, JPEG y PNG.

Estrategia:
1) Si el PDF contiene texto digital, usa PyMuPDF.
2) Si el PDF tiene poco o ningún texto, usa Tesseract OCR.
3) Las imágenes siempre pasan por Tesseract OCR.

Normalmente solo necesitás cambiar TESSERACT_CMD o TESSERACT_LANG en config.py.
"""

from __future__ import annotations

import io
from typing import Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

from config import MIN_TEXT_LENGTH, TESSERACT_CMD, TESSERACT_LANG


# CAMBIAR desde config.py si Tesseract está instalado en otra ruta.
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _normalizar_texto(texto: str) -> str:
    """
    Limpia espacios repetidos pero mantiene saltos de línea,
    porque ayudan al parser a encontrar datos por contexto.
    """
    lineas = []
    for linea in texto.splitlines():
        limpia = " ".join(linea.split())
        if limpia:
            lineas.append(limpia)

    return "\n".join(lineas)


def extraer_texto_pdf(archivo: io.BytesIO) -> Tuple[str, str]:
    """
    Devuelve:
        texto
        metodo utilizado: "PDF_TEXTO" u "OCR"
    """
    contenido = archivo.getvalue()

    documento = fitz.open(
        stream=contenido,
        filetype="pdf",
    )

    texto_digital = []
    for pagina in documento:
        texto_digital.append(pagina.get_text("text"))

    texto = _normalizar_texto("\n".join(texto_digital))

    if len(texto.strip()) >= MIN_TEXT_LENGTH:
        return texto, "PDF_TEXTO"

    # Si el PDF no trae suficiente texto, hacemos OCR página por página.
    paginas_ocr = []

    for pagina in documento:
        # 2x mejora la resolución para OCR sin complicar demasiado el proceso.
        pix = pagina.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

        imagen = Image.open(
            io.BytesIO(pix.tobytes("png"))
        )

        texto_pagina = pytesseract.image_to_string(
            imagen,
            lang=TESSERACT_LANG,
        )

        paginas_ocr.append(texto_pagina)

    texto_ocr = _normalizar_texto("\n".join(paginas_ocr))
    return texto_ocr, "OCR"


def extraer_texto_imagen(archivo: io.BytesIO) -> Tuple[str, str]:
    """
    Ejecuta OCR sobre JPG, JPEG o PNG.
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
    Detecta si el archivo es PDF o imagen.
    """
    mime_type = (mime_type or "").lower()
    extension = nombre_archivo.lower().split(".")[-1] if "." in nombre_archivo else ""

    if mime_type == "application/pdf" or extension == "pdf":
        return extraer_texto_pdf(archivo)

    if mime_type.startswith("image/") or extension in {"jpg", "jpeg", "png"}:
        return extraer_texto_imagen(archivo)

    raise ValueError(
        f"Formato no soportado: {mime_type or extension}. "
        "Usá PDF, JPG, JPEG o PNG."
    )
