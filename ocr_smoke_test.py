"""Comprueba inferencia real con datos sintéticos, sin Google ni fallback."""

from PIL import Image, ImageDraw, ImageFont

from extractor import _ocr_paddle


def main():
    image = Image.new("RGB", (640, 160), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    ImageDraw.Draw(image).text((25, 45), "FACTURA A TOTAL 121,00", font=font, fill="black")
    result = _ocr_paddle(image, 1)
    if "FACTURA" not in result["texto"].upper():
        raise RuntimeError("PaddleOCR no pudo leer la imagen sintética")
    print("PaddleOCR: inferencia sintética correcta")


if __name__ == "__main__":
    main()
