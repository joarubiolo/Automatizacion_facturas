"""
EXTRACTOR V10
=============
Arquitectura:

PDF/imagen
   |
   +-- Si PyMuPDF encuentra texto digital suficiente -> PDF_TEXTO
   |
   +-- Si no -> PaddleOCR (texto + bounding boxes + confianza)
                 |
                 +-- si Paddle falla -> Tesseract opcional

La salida de extraer_documento() es siempre un diccionario normalizado:
{
    "texto": "...",
    "metodo": "PDF_TEXTO" | "PADDLEOCR" | "TESSERACT_FALLBACK",
    "tokens": [...],
    "lineas": [...],
    "paginas": [...]
}
"""

from __future__ import annotations

import io
import re
from functools import lru_cache
from typing import Dict, List, Tuple, Any

import numpy as np
import pymupdf
from PIL import Image

import config


def _normalizar_texto(texto: str) -> str:
    return "\n".join(
        linea.rstrip()
        for linea in str(texto or "").splitlines()
        if linea.strip()
    )


def _zona_por_y(y_rel: float) -> str:
    if y_rel < 0.28:
        return "CABECERA"
    if y_rel < 0.46:
        return "CLIENTE"
    if y_rel < 0.75:
        return "DETALLE"
    if y_rel < 0.91:
        return "TOTALES"
    return "PIE"


def _resultado_a_dict(res: Any) -> Dict:
    """
    PaddleOCR 3.x devuelve objetos Result.
    Esta función tolera varias representaciones para reducir acoplamiento
    con cambios menores de versión.
    """
    if isinstance(res, dict):
        return res.get("res", res)

    for attr in ("json", "res"):
        try:
            value = getattr(res, attr)
            if callable(value):
                value = value()
            if isinstance(value, dict):
                return value.get("res", value)
        except Exception:
            pass

    for method in ("to_dict", "dict"):
        try:
            value = getattr(res, method)()
            if isinstance(value, dict):
                return value.get("res", value)
        except Exception:
            pass

    raise TypeError(
        "No se pudo convertir el resultado de PaddleOCR a diccionario."
    )


@lru_cache(maxsize=1)
def _get_paddle():
    from paddleocr import PaddleOCR

    kwargs = {
        "lang": getattr(config, "PADDLE_LANG", "es"),
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "device": getattr(config, "PADDLE_DEVICE", "cpu"),
        "text_detection_model_name": getattr(
            config,
            "PADDLE_DET_MODEL",
            "PP-OCRv5_mobile_det",
        ),
        "text_recognition_model_name": getattr(
            config,
            "PADDLE_REC_MODEL",
            "latin_PP-OCRv5_mobile_rec",
        ),
        "text_recognition_batch_size": getattr(
            config,
            "PADDLE_REC_BATCH_SIZE",
            1,
        ),
        "text_det_limit_side_len": getattr(
            config,
            "PADDLE_DET_LIMIT_SIDE_LEN",
            1600,
        ),
        "text_det_limit_type": "max",
    }

    return PaddleOCR(**kwargs)


def _paddle_tokens(imagen: Image.Image, pagina: int) -> List[Dict]:
    ocr = _get_paddle()

    arr = np.asarray(imagen.convert("RGB"))
    resultados = ocr.predict(arr)

    tokens: List[Dict] = []
    min_score = float(getattr(config, "PADDLE_MIN_SCORE", 0.35))
    ancho, alto = imagen.size

    for res in resultados:
        data = _resultado_a_dict(res)

        textos = list(data.get("rec_texts") or [])
        scores = list(data.get("rec_scores") or [])
        boxes = data.get("rec_boxes")

        if boxes is None:
            polys = data.get("rec_polys") or []
            boxes = []
            for poly in polys:
                puntos = np.asarray(poly)
                xs = puntos[:, 0]
                ys = puntos[:, 1]
                boxes.append([
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max()),
                    int(ys.max()),
                ])

        boxes = np.asarray(boxes).tolist() if len(boxes) else []

        cantidad = min(len(textos), len(scores), len(boxes))

        for i in range(cantidad):
            texto = str(textos[i]).strip()
            score = float(scores[i])
            if not texto or score < min_score:
                continue

            x0, y0, x1, y1 = [float(v) for v in boxes[i]]
            y_rel = y0 / alto if alto else 0
            x_rel = x0 / ancho if ancho else 0

            tokens.append({
                "texto": texto,
                "conf": score,
                "x": x0,
                "y": y0,
                "w": max(0.0, x1 - x0),
                "h": max(0.0, y1 - y0),
                "x_rel": x_rel,
                "y_rel": y_rel,
                "pagina": pagina,
                "zona": _zona_por_y(y_rel),
                "motor": "PADDLEOCR",
            })

    return tokens


def _agrupar_lineas(tokens: List[Dict]) -> List[Dict]:
    """
    PaddleOCR devuelve cajas de texto. Las reagrupamos por proximidad vertical
    para reconstruir filas/lineas de factura.
    """
    if not tokens:
        return []

    por_pagina = {}
    for t in tokens:
        por_pagina.setdefault(t["pagina"], []).append(t)

    salida = []

    for pagina, items in por_pagina.items():
        items = sorted(items, key=lambda t: (t["y"], t["x"]))
        alturas = [max(1.0, float(t["h"])) for t in items]
        altura_mediana = float(np.median(alturas)) if alturas else 12.0
        tolerancia = max(5.0, altura_mediana * 0.65)

        grupos = []

        for token in items:
            cy = token["y"] + token["h"] / 2

            elegido = None
            mejor_dist = None

            for grupo in grupos:
                dist = abs(cy - grupo["cy"])
                if dist <= tolerancia and (
                    mejor_dist is None or dist < mejor_dist
                ):
                    elegido = grupo
                    mejor_dist = dist

            if elegido is None:
                grupos.append({
                    "cy": cy,
                    "tokens": [token],
                })
            else:
                elegido["tokens"].append(token)
                elegido["cy"] = np.mean([
                    x["y"] + x["h"] / 2
                    for x in elegido["tokens"]
                ])

        for grupo in grupos:
            fila = sorted(grupo["tokens"], key=lambda t: t["x"])
            texto = " ".join(t["texto"] for t in fila).strip()

            if not texto:
                continue

            salida.append({
                "texto": texto,
                "conf": float(np.mean([t["conf"] for t in fila])),
                "pagina": pagina,
                "zona": fila[0]["zona"],
                "x_rel": min(t["x_rel"] for t in fila),
                "y_rel": min(t["y_rel"] for t in fila),
                "tokens": fila,
            })

    return sorted(salida, key=lambda l: (l["pagina"], l["y_rel"], l["x_rel"]))


def _ocr_paddle(imagen: Image.Image, pagina: int) -> Dict:
    tokens = _paddle_tokens(imagen, pagina)
    lineas = _agrupar_lineas(tokens)
    texto = _normalizar_texto("\n".join(l["texto"] for l in lineas))

    return {
        "texto": texto,
        "tokens": tokens,
        "lineas": lineas,
        "motor": "PADDLEOCR",
    }


def _ocr_tesseract(imagen: Image.Image, pagina: int) -> Dict:
    """
    Fallback únicamente. No es el motor principal.
    """
    import pytesseract
    from pytesseract import Output

    pytesseract.pytesseract.tesseract_cmd = getattr(
        config,
        "TESSERACT_CMD",
        "tesseract",
    )

    datos = pytesseract.image_to_data(
        imagen,
        lang=getattr(config, "TESSERACT_LANG", "spa"),
        config="--oem 3 --psm 6",
        output_type=Output.DICT,
    )

    ancho, alto = imagen.size
    tokens = []

    for i, texto in enumerate(datos.get("text", [])):
        texto = str(texto).strip()
        if not texto:
            continue

        try:
            score = max(0.0, float(datos["conf"][i]) / 100.0)
        except Exception:
            score = 0.0

        x = float(datos["left"][i])
        y = float(datos["top"][i])
        w = float(datos["width"][i])
        h = float(datos["height"][i])
        y_rel = y / alto if alto else 0

        tokens.append({
            "texto": texto,
            "conf": score,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "x_rel": x / ancho if ancho else 0,
            "y_rel": y_rel,
            "pagina": pagina,
            "zona": _zona_por_y(y_rel),
            "motor": "TESSERACT",
        })

    lineas = _agrupar_lineas(tokens)
    return {
        "texto": _normalizar_texto("\n".join(l["texto"] for l in lineas)),
        "tokens": tokens,
        "lineas": lineas,
        "motor": "TESSERACT",
    }


def _imagen_de_pagina(pagina) -> Image.Image:
    escala = float(getattr(config, "OCR_SCALE", 2.5))
    pix = pagina.get_pixmap(
        matrix=pymupdf.Matrix(escala, escala),
        alpha=False,
    )
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def _ocr_con_fallback(imagen: Image.Image, pagina: int) -> Dict:
    try:
        resultado = _ocr_paddle(imagen, pagina)
        if resultado["texto"].strip():
            return resultado
    except Exception as paddle_error:
        if not getattr(config, "USE_TESSERACT_FALLBACK", True):
            raise

        fallback = _ocr_tesseract(imagen, pagina)
        fallback["error_paddle"] = str(paddle_error)
        return fallback

    if getattr(config, "USE_TESSERACT_FALLBACK", True):
        return _ocr_tesseract(imagen, pagina)

    return {
        "texto": "",
        "tokens": [],
        "lineas": [],
        "motor": "PADDLEOCR",
    }


def extraer_documento(
    archivo: io.BytesIO,
    mime_type: str,
    nombre_archivo: str = "",
) -> Dict:
    mime_type = (mime_type or "").lower()
    extension = (
        nombre_archivo.lower().rsplit(".", 1)[-1]
        if "." in nombre_archivo
        else ""
    )

    # ---------------------------------------------------------
    # PDF
    # ---------------------------------------------------------
    if mime_type == "application/pdf" or extension == "pdf":
        contenido = archivo.getvalue()
        doc = pymupdf.open(stream=contenido, filetype="pdf")

        texto_paginas = [
            pagina.get_text("text", sort=True)
            for pagina in doc
        ]

        texto_digital = _normalizar_texto("\n".join(texto_paginas))

        if len(texto_digital) >= int(getattr(config, "MIN_TEXT_LENGTH", 100)):
            return {
                "texto": texto_digital,
                "metodo": "PDF_TEXTO",
                "tokens": [],
                "lineas": [],
                "paginas": [],
            }

        paginas = []
        todos_tokens = []
        todas_lineas = []

        for indice, pagina in enumerate(doc, start=1):
            imagen = _imagen_de_pagina(pagina)
            r = _ocr_con_fallback(imagen, indice)
            paginas.append(r)
            todos_tokens.extend(r["tokens"])
            todas_lineas.extend(r["lineas"])

        metodo = (
            "PADDLEOCR"
            if paginas and all(p["motor"] == "PADDLEOCR" for p in paginas)
            else "OCR_MIXTO/FALLBACK"
        )

        return {
            "texto": _normalizar_texto(
                "\n".join(p["texto"] for p in paginas)
            ),
            "metodo": metodo,
            "tokens": todos_tokens,
            "lineas": todas_lineas,
            "paginas": paginas,
        }

    # ---------------------------------------------------------
    # Imagen
    # ---------------------------------------------------------
    if mime_type.startswith("image/") or extension in {"jpg", "jpeg", "png"}:
        archivo.seek(0)
        imagen = Image.open(archivo).convert("RGB")
        r = _ocr_con_fallback(imagen, 1)

        return {
            "texto": r["texto"],
            "metodo": r["motor"],
            "tokens": r["tokens"],
            "lineas": r["lineas"],
            "paginas": [r],
        }

    raise ValueError(
        f"Formato no soportado: {mime_type or extension}. "
        "Usá PDF, JPG, JPEG o PNG."
    )


def extraer_texto(
    archivo: io.BytesIO,
    mime_type: str,
    nombre_archivo: str = "",
) -> Tuple[str, str]:
    """
    Compatibilidad hacia atrás.
    """
    documento = extraer_documento(
        archivo,
        mime_type,
        nombre_archivo,
    )
    return documento["texto"], documento["metodo"]
