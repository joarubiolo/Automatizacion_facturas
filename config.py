"""
CONFIGURACIÓN GENERAL DE LA AUTOMATIZACIÓN.

IMPORTANTE:
Buscá los comentarios que dicen "# CAMBIAR:".
Esas son las partes que tenés que completar para que funcione en tu cuenta.
"""

# ============================================================
# GOOGLE DRIVE
# ============================================================

# CAMBIAR: pegá solamente el ID de la carpeta "01_ENTRADA".
# Ejemplo de URL:
# https://drive.google.com/drive/folders/1AbCdEfGh123456
# El ID sería: 1AbCdEfGh123456
INPUT_FOLDER_ID = "1LqovQ-ywyaA3144EJhULaJk_deROpjY4"

# CAMBIAR: ID de la carpeta "02_PROCESADAS".
PROCESSED_FOLDER_ID = "10qA0mQMhXSjJ0iXWD8Zc2HifP77SFefY"

# CAMBIAR: ID de la carpeta "03_REVISAR".
REVIEW_FOLDER_ID = "1fQ2dx5AJBdSQMrXtXkZwR9847C4StKdU"


# ============================================================
# GOOGLE SHEETS
# ============================================================

# CAMBIAR: pegá el ID de tu Google Sheet "Registro de Facturas".
# Ejemplo:
# https://docs.google.com/spreadsheets/d/1ABCxyz123/edit
# El ID sería: 1ABCxyz123
SPREADSHEET_ID = "1MiWkU38vtO8DdILg6kDvXz-xLYcWKj9bcjsOQtZUyNQ"

# CAMBIAR solamente si tu pestaña tiene otro nombre.
WORKSHEET_NAME = "Facturas"


# ============================================================
# CREDENCIALES GOOGLE
# ============================================================

# CAMBIAR solamente si tu archivo JSON tiene otro nombre o está en otra carpeta.
# NO subas este archivo a GitHub.
SERVICE_ACCOUNT_FILE = "credentials/service_account.json"


# ============================================================
# OCR / TESSERACT
# ============================================================

# CAMBIAR si Tesseract está instalado en otra ruta.
# Ruta típica en Windows:
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# CAMBIAR a "eng" si no instalaste el paquete de idioma español de Tesseract.
TESSERACT_LANG = "spa"


# ============================================================
# AUTOMATIZACIÓN
# ============================================================

# Cada cuántos segundos Streamlit vuelve a revisar Google Drive.
POLL_SECONDS = 30

# Cantidad mínima de caracteres extraídos de un PDF para considerar
# que el PDF ya contiene texto digital y NO hace falta OCR.
MIN_TEXT_LENGTH = 100
