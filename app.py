"""
Aplicación principal Streamlit.

El usuario NO confirma facturas.
El flujo es automático:

Google Drive / 01_ENTRADA
        ↓
descarga
        ↓
PDF texto u OCR
        ↓
parser
        ↓
validación
        ↓
Google Sheets
        ↓
02_PROCESADAS o 03_REVISAR

Para ejecutarla:
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st
from datetime import datetime

from config import POLL_SECONDS
from pipeline import ejecutar_ciclo


st.set_page_config(
    page_title="Automatización de Facturas",
    page_icon="🧾",
    layout="wide",
)

st.title("🧾 Automatización de Facturas")
st.caption(
    "La aplicación revisa Google Drive automáticamente y carga "
    "las facturas en Google Sheets."
)


# Streamlit vuelve a ejecutar este fragmento cada POLL_SECONDS segundos.
@st.fragment(run_every=f"{POLL_SECONDS}s")
def monitor():
    st.subheader("Estado")

    try:
        archivos, resultados = ejecutar_ciclo()

        col1, col2, col3 = st.columns(3)

        col1.metric("Pendientes detectadas", len(archivos))
        col2.metric("Procesadas en este ciclo", len(resultados))
        col3.metric(
            "Última revisión",
            datetime.now().strftime("%H:%M:%S"),
        )

        if resultados:
            st.subheader("Últimos resultados")

            st.dataframe(
                resultados,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success(
                "No hay facturas nuevas en 01_ENTRADA."
            )

    except Exception as exc:
        st.error(
            "No se pudo ejecutar la automatización.\n\n"
            f"Detalle: {exc}"
        )

        st.info(
            "Revisá config.py, el archivo credentials/service_account.json, "
            "los permisos de Drive y los permisos del Google Sheet."
        )


monitor()
