import config
from extractor import _get_paddle

_get_paddle()
if config.PADDLE_NUMERIC_REC_MODEL:
    _get_paddle(config.PADDLE_NUMERIC_REC_MODEL)

print("Modelos PaddleOCR descargados y listos.")
