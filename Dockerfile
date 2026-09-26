FROM python:3.11-slim


# ============================================================
# Instalar Tesseract + idioma español
# ============================================================

RUN apt-get update && \
    apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-spa && \
    rm -rf /var/lib/apt/lists/*


# ============================================================
# Carpeta de la aplicación
# ============================================================

WORKDIR /app


# ============================================================
# Instalar dependencias Python
# ============================================================

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt


# ============================================================
# Copiar aplicación
# ============================================================

COPY . .


# ============================================================
# Ejecutar Streamlit
# Render proporciona automáticamente la variable PORT.
# ============================================================

CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-10000}"]