import os

# ============================================================
# GOOGLE DRIVE
# ============================================================

# En Render estos valores se toman de Environment Variables.
# Localmente podés reemplazar el segundo parámetro por tus IDs actuales
# si querés seguir ejecutándolo sin variables de entorno.

INPUT_FOLDER_ID = os.getenv(
    "1LqovQ-ywyaA3144EJhULaJk_deROpjY4",
    "PEGAR_ID_CARPETA_01_ENTRADA"
)

PROCESSED_FOLDER_ID = os.getenv(
    "10qA0mQMhXSjJ0iXWD8Zc2HifP77SFefY",
    "PEGAR_ID_CARPETA_02_PROCESADAS"
)

REVIEW_FOLDER_ID = os.getenv(
    "1fQ2dx5AJBdSQMrXtXkZwR9847C4StKdU",
    "PEGAR_ID_CARPETA_03_REVISAR"
)


# ============================================================
# GOOGLE SHEETS
# ============================================================

SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "1CaV_p2wr9G4lHfZBiHWzRbBgzUYqSFFCrwyF5u7rKDE"
)

WORKSHEET_NAME = os.getenv(
    "WORKSHEET_NAME",
    "Facturas"
)


# ============================================================
# GOOGLE SERVICE ACCOUNT
# ============================================================

# LOCAL:
# credentials/service_account.json
#
# RENDER:
# /etc/secrets/service_account.json

SERVICE_ACCOUNT_FILE = os.getenv(
    "SERVICE_ACCOUNT_FILE",
    "credentials/service_account.json"
)


# ============================================================
# TESSERACT
# ============================================================

# Windows local:
# C:\Program Files\Tesseract-OCR\tesseract.exe
#
# Render/Docker Linux:
# tesseract

if os.getenv("RENDER"):
    TESSERACT_CMD = "tesseract"
else:
    TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


TESSERACT_LANG = os.getenv(
    "TESSERACT_LANG",
    "spa"
)


# ============================================================
# AUTOMATIZACIÓN
# ============================================================

POLL_SECONDS = int(
    os.getenv("POLL_SECONDS", "30")
)

MIN_TEXT_LENGTH = int(
    os.getenv("MIN_TEXT_LENGTH", "100")
)
