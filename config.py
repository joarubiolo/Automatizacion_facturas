import os
import platform

INPUT_FOLDER_ID = os.getenv("INPUT_FOLDER_ID")
PROCESSED_FOLDER_ID = os.getenv("PROCESSED_FOLDER_ID")
REVIEW_FOLDER_ID = os.getenv("REVIEW_FOLDER_ID")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "FACTURAS")
SERVICE_ACCOUNT_FILE = os.getenv(
    "SERVICE_ACCOUNT_FILE",
    "credentials/service_account.json",
)

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
MIN_TEXT_LENGTH = int(os.getenv("MIN_TEXT_LENGTH", "100"))

PADDLE_LANG = os.getenv("PADDLE_LANG", "es")
PADDLE_DEVICE = os.getenv("PADDLE_DEVICE", "cpu")
PADDLE_ENABLE_MKLDNN = os.getenv(
    "PADDLE_ENABLE_MKLDNN",
    "false" if platform.machine().lower() in {"aarch64", "arm64"} else "true",
).lower() == "true"
PADDLE_CPU_THREADS = int(os.getenv("PADDLE_CPU_THREADS", "1"))
PADDLE_MIN_SCORE = float(os.getenv("PADDLE_MIN_SCORE", "0.35"))

PADDLE_DET_MODEL = os.getenv(
    "PADDLE_DET_MODEL",
    "PP-OCRv5_mobile_det",
)
PADDLE_REC_MODEL = os.getenv(
    "PADDLE_REC_MODEL",
    "latin_PP-OCRv5_mobile_rec",
)
PADDLE_REC_BATCH_SIZE = int(
    os.getenv("PADDLE_REC_BATCH_SIZE", "1")
)
PADDLE_DET_LIMIT_SIDE_LEN = int(
    os.getenv("PADDLE_DET_LIMIT_SIDE_LEN", "1600")
)

OCR_SCALE = float(os.getenv("OCR_SCALE", "2.0"))
OCR_REGION_SCALE = float(os.getenv("OCR_REGION_SCALE", "3.0"))
OCR_REFINE_REGIONS = os.getenv("OCR_REFINE_REGIONS", "true").lower() == "true"
PADDLE_NUMERIC_REC_MODEL = os.getenv("PADDLE_NUMERIC_REC_MODEL", "PP-OCRv5_server_rec")

if platform.system() == "Windows":
    TESSERACT_CMD = os.getenv(
        "TESSERACT_CMD",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    )
else:
    TESSERACT_CMD = os.getenv(
        "TESSERACT_CMD",
        "/usr/bin/tesseract",
    )

TESSERACT_LANG = os.getenv("TESSERACT_LANG", "spa")
USE_TESSERACT_FALLBACK = (
    os.getenv("USE_TESSERACT_FALLBACK", "true").lower() == "true"
)
