FROM python:3.11-slim


# ============================================================
# Variables generales
# ============================================================

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# IMPORTANTE:
# Ruta de Tesseract dentro del contenedor Linux
ENV TESSERACT_CMD=/usr/bin/tesseract
ENV TESSERACT_LANG=spa


# ============================================================
# Instalar Tesseract + idioma español
# ============================================================

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-spa && \
    rm -rf /var/lib/apt/lists/*


# ============================================================
# Verificar que Tesseract realmente quedó instalado
# ============================================================

RUN which tesseract && \
    tesseract --version && \
    tesseract --list-langs


# ============================================================
# Carpeta de la aplicación
# ============================================================

WORKDIR /app


# ============================================================
# Instalar dependencias Python
# ============================================================

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ============================================================
# Copiar aplicación
# ============================================================

COPY . .


# ============================================================
# Puerto de Render
# ============================================================

EXPOSE 10000


# ============================================================
# Ejecutar Streamlit
# ============================================================

CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT:-10000} --server.headless=true"]
