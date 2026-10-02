# Automatización de facturas

Aplicación Streamlit que toma facturas de Google Drive, extrae y valida sus datos,
las registra en Google Sheets y mueve los archivos a PROCESADAS o REVISAR.

## Flujo

1. PyMuPDF extrae texto de PDFs digitales.
2. PaddleOCR procesa PDFs escaneados e imágenes, conservando posiciones y confianza.
3. Tesseract se utiliza como respaldo si PaddleOCR falla o no devuelve texto.
4. El motor de inferencia interpreta el documento; el validador comprueba campos,
   CUIT y la suma `neto + iva + importe_otros_tributos = total`.
5. `OK` y `OK_INFERIDO` van a PROCESADAS; `REVISAR` va a revisión.

### Lectura de tablas y escaneos

Los escaneos se leen en franjas superpuestas a mayor resolución, conservando
las coordenadas de página y evitando duplicar líneas. El concepto se obtiene
de la columna DESCRIPCIÓN, hasta el comienzo del resumen financiero; no incluye
leyendas de recibo ni pagos.

El OCR latino conserva el texto en español. Una segunda lectura con
`PP-OCRv5_server_rec` se aplica a precios, resumen financiero y total en letras.
Los importes se asocian por columnas y se contrastan al centavo con el total,
la alícuota y, si no hay descuentos, cantidades por precios unitarios. Un neto
reconstruido desde artículos queda identificado como inferido. Los importes
explícitos contradictorios se conservan para revisión: no se modifica el IVA
solo para hacer cuadrar la suma.

Los ajustes están en `.env.example`. Los tres modelos se descargan durante el
build; no se envían facturas a servicios OCR externos. Referencias de los motores:
[parámetros de PaddleOCR](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/OCR.html),
[modelos de reconocimiento](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/module_usage/text_recognition.html)
y [calidad de imagen en Tesseract](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html).

Verificación del 2 de octubre de 2026: el escaneo de referencia devuelve ambos
conceptos, neto 186.300,00, IVA 39.123,00, otros 0,00 y total 225.423,00 en la
prueba local. Sigue en REVISAR por el tipo de comprobante no detectado; el número
tampoco debe considerarse verificado. La prueba con una factura no garantiza
la misma precisión en otros formatos.

**Oracle Cloud:** el modo `worker.py` procesa periódicamente sin navegador abierto.
La instalación está en [ORACLE_DEPLOY.md](ORACLE_DEPLOY.md). `compose.oracle.yaml`
configura un único proceso ARM64, reinicio automático y credenciales montadas.

**Streamlit:** `app.py` conserva el modo interactivo, que necesita una sesión
abierta. Usar un único modo de procesamiento por carpeta para evitar ejecuciones
simultáneas; detener Render antes de activar el worker de Oracle.

## Archivos del proyecto

| Archivos | Función |
| --- | --- |
| `app.py`, `config.py`, `pipeline.py`, `worker.py` | Interfaz, configuración y procesamiento compartido/continuo |
| `extractor.py`, `inference_engine.py`, `parser.py`, `validator.py` | Extracción, inferencia y validación |
| `google_services.py` | Google Drive y Sheets |
| `Dockerfile`, `.dockerignore`, `requirements.txt`, `preload_paddle_models.py` | Imagen y precarga de modelos |
| `render.yaml`, `RENDER_ENV.txt`, `INSTRUCCIONES_RENDER.txt` | Configuración de Render |
| `compose.oracle.yaml`, `.env.example`, `deploy/`, `ORACLE_DEPLOY.md` | Instalación en Oracle ARM64 |
| `test_conexion.py`, `test_factura_local.py`, `ocr_smoke_test.py`, `tests/` | Diagnóstico y regresiones |

No se publican credenciales, facturas reales, resultados JSON, cachés, respaldos
del parser/validador ni el PDF de conversación. Esos archivos permanecen locales.

## Configuración de Google

- Habilitar Google Drive API y Google Sheets API para la cuenta de servicio.
- Compartir las carpetas de entrada/procesadas/revisión y la planilla con esa
  cuenta, con permiso de editor.
- Configurar `INPUT_FOLDER_ID`, `PROCESSED_FOLDER_ID`, `REVIEW_FOLDER_ID` y
  `SPREADSHEET_ID` como variables de entorno.
- Crear la pestaña `FACTURAS` o ajustar `WORKSHEET_NAME` al nombre exacto.
- En la primera fila, colocar estos encabezados, en este orden:

```text
fecha_carga,estado,fecha_factura,tipo,punto_venta,numero,proveedor,cuit_proveedor,cliente,cuit_cliente,detalle,neto,iva,importe_otros_tributos,total,cae,vencimiento_cae,archivo,drive_id,hash,clave_factura,observaciones
```

## Docker

La imagen usa Python 3.11, PaddlePaddle 3.2.0 CPU y PaddleOCR 3.3.1. El primer
build necesita Internet para instalar dependencias y descargar modelos.

```powershell
docker build -t facturas-render .
docker run --rm facturas-render python -m unittest discover -s tests -v
docker run --rm --mount "type=bind,source=${PWD}/facturas_prueba,target=/facturas,readonly" facturas-render python test_factura_local.py "/facturas/factura ejemplo 4.pdf"
```

Para ejecutar la app localmente, copiar `RENDER_ENV.txt` a `.env`, completar los
IDs y cambiar `SERVICE_ACCOUNT_FILE` a `/run/secrets/service_account.json`:

```powershell
docker run --rm -p 10000:10000 --env-file .env --mount "type=bind,source=${PWD}/credentials/service_account.json,target=/run/secrets/service_account.json,readonly" facturas-render
```

Abrir `http://localhost:10000`. La app comienza a procesar la carpeta configurada
al abrir la sesión. El archivo `.env` se inyecta mediante Docker; Python no lo
carga automáticamente.

## Render

Usar un Web Service con runtime Docker y este repositorio. La configuración
detallada está en `INSTRUCCIONES_RENDER.txt`; `RENDER_ENV.txt` contiene las variables.

El Blueprint solicita los cuatro IDs al crearse, mediante
[`sync: false`](https://render.com/docs/blueprint-spec#prompting-for-secret-values).
Para servicios existentes, configurar esos valores desde el panel.

Agregar `service_account.json` como Secret File en Render y usar
`SERVICE_ACCOUNT_FILE=/etc/secrets/service_account.json`. Nunca subir el JSON al
repositorio. El plan `2c-4g` del Blueprint es pago; publicar este repositorio no
crea ni contrata un servicio. El health check es `/_stcore/health`.

## Verificación sin Google

Con las dependencias instaladas:

```powershell
python -m unittest discover -s tests -v
```

Las pruebas usan datos sintéticos y sustituyen los servicios de Google. Para una
factura privada, ejecutar `test_factura_local.py` con su ruta. Para comprobar las
credenciales, ejecutar `test_conexion.py` con las variables de entorno configuradas.

### Resultado de la revisión del 1 de octubre de 2026

- Imagen Docker construida correctamente, con ambos modelos precargados.
- Ocho pruebas aprobadas en Python local y dentro de Docker; `pip check` correcto.
- La factura escaneada disponible se procesó con PaddleOCR, sin red, y terminó
  en `REVISAR`. No detectó el tipo y extrajo incorrectamente algunos campos,
  incluidos número e importes. Esa muestra todavía necesita mejorar el OCR y
  las reglas de interpretación antes de automatizar su registro sin revisión.
- Las pruebas no escribieron en Google Drive ni en Sheets. La conexión real y
  el despliegue en Render requieren la configuración de cada entorno.
