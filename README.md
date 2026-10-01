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

**Funcionamiento actual:** la revisión periódica usa un fragmento de Streamlit
asociado a una sesión abierta. No es un worker independiente que garantice
procesamiento permanente con el navegador cerrado. Usar una única sesión de
procesamiento para evitar ejecuciones simultáneas.

## Archivos del proyecto

| Archivos | Función |
| --- | --- |
| `app.py`, `config.py` | Aplicación y variables de entorno |
| `extractor.py`, `inference_engine.py`, `parser.py`, `validator.py` | Extracción, inferencia y validación |
| `google_services.py` | Google Drive y Sheets |
| `Dockerfile`, `.dockerignore`, `requirements.txt`, `preload_paddle_models.py` | Imagen y precarga de modelos |
| `render.yaml`, `RENDER_ENV.txt`, `INSTRUCCIONES_RENDER.txt` | Configuración de Render |
| `test_conexion.py`, `test_factura_local.py`, `tests/` | Diagnóstico y regresiones |

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
