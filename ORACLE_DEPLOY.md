# Oracle Cloud Always Free: instalación

La aplicación se ejecuta como un único worker Docker, sin navegador ni puertos
web públicos. Revisa Google Drive periódicamente y escribe los resultados en
Google Sheets. Streamlit sigue disponible para el modo interactivo anterior;
no ejecutar ambos modos contra las mismas carpetas al mismo tiempo.

## 1. Cuenta e instancia

Crear la cuenta en https://www.oracle.com/cloud/free/. La verificación de identidad
y tarjeta debe hacerla el titular, directamente en Oracle.

En Compute > Instances > Create instance, elegir:

| Campo | Valor |
| --- | --- |
| Nombre | `automatizacion-facturas` |
| Imagen | Ubuntu 24.04 ARM64 |
| Shape | `VM.Standard.A1.Flex`, Ampere ARM |
| OCPU | 2 |
| Memoria | 12 GB |
| Disco de arranque | 50 GB, dentro del cupo gratuito total de 200 GB |
| Región | Home region de la cuenta |
| Red | Subred pública con Internet Gateway e IP pública para SSH |
| Acceso de entrada | TCP 22 solamente desde tu IP pública (`TU_IP/32`) |
| SSH | Generar/guardar el par de claves o cargar una clave pública propia |

Comprobar en la consola que los recursos queden dentro de Always Free y no
agregar servicios pagos. El cupo total actual de A1 es 2 OCPU y 12 GB, contando
todas las instancias A1 de la cuenta. No usar el crédito temporal de prueba como
garantía de gratuidad permanente. Si no hay capacidad A1 gratuita, esperar o
probar otro dominio de disponibilidad de la misma región.

Oracle puede recuperar instancias que considere inactivas. Las condiciones y
límites deben revisarse en la consola antes de crear recursos:
[Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Se necesita salida HTTPS para GitHub, repositorios de paquetes, modelos OCR y
Google APIs. No hace falta abrir los puertos 80, 443 ni 10000 de entrada.

## 2. Conectarse e instalar Docker

Desde PowerShell, reemplazar IP y ruta de la clave privada:

```powershell
ssh -i "C:\ruta\oracle.key" ubuntu@IP_PUBLICA
```

En la VM Ubuntu nueva:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/joarubiolo/Automatizacion_facturas.git
cd Automatizacion_facturas
sudo bash deploy/oracle-bootstrap.sh
```

El instalador usa el repositorio oficial de Docker para Ubuntu ARM64 y habilita
Docker al arrancar la VM. Referencia: [instalación oficial](https://docs.docker.com/engine/install/ubuntu/).
Está pensado para una VM nueva, sin otra instalación de Docker.

## 3. Variables y credenciales privadas

En la VM:

```bash
umask 077
mkdir -p credentials
cp .env.example .env
nano .env
```

Completar los cuatro IDs de Drive/Sheets y el nombre exacto de la pestaña.
Mantener inicialmente `POLL_SECONDS=60` y el perfil OCR mobile.

Desde otra terminal PowerShell, en la carpeta local del proyecto:

```powershell
scp -i "C:\ruta\oracle.key" .\credentials\service_account.json ubuntu@IP_PUBLICA:~/Automatizacion_facturas/credentials/service_account.json
```

Volver a la VM:

```bash
chmod 600 .env credentials/service_account.json
sudo docker compose -f compose.oracle.yaml config --quiet
sudo docker compose -f compose.oracle.yaml build
sudo docker compose -f compose.oracle.yaml run --rm --no-deps worker python -m unittest discover -s tests -v
sudo docker compose -f compose.oracle.yaml run --rm --no-deps worker python ocr_smoke_test.py
```

El build descarga los modelos. Compose monta el JSON como secreto de solo lectura;
no se copia dentro de la imagen. La cuenta de servicio debe tener acceso a las
carpetas y la planilla, con los encabezados del README.

La prueba OCR usa una imagen sintética y no accede a Google. Debe mostrar
`PaddleOCR: inferencia sintética correcta` antes de iniciar el procesamiento real.
El perfil ARM usa un hilo de CPU y desactiva MKLDNN. Si la prueba falla, no iniciar
el worker: revisar primero la compatibilidad del motor con la VM.

## 4. Iniciar procesamiento

Detener el servicio anterior de Render antes de iniciar el worker, para que no
haya dos procesos trabajando sobre las mismas facturas.

Para comprobar configuración y procesar un solo ciclo (modifica Drive y Sheets):

```bash
sudo docker compose -f compose.oracle.yaml run --rm --no-deps worker python worker.py --once
```

Para dejarlo funcionando:

```bash
sudo docker compose -f compose.oracle.yaml up -d
sudo docker compose -f compose.oracle.yaml logs --tail=100 -f worker
```

Después de `up -d` se puede cerrar SSH y apagar la PC local. El worker sigue en
Oracle y Docker lo reinicia si falla o si reinicia la VM. Los logs muestran
cantidades por estado, sin nombres de archivos, CUIT ni contenido de facturas.
`REVISAR` es un resultado de validación, no un fallo del servicio.

El worker espera 60 segundos después de cada ciclo. No hay procesos paralelos
para una misma carpeta. Usa hasta 8 GB de memoria y 2 CPU; el resto de la memoria
queda disponible para el sistema. No se inicia un servidor Streamlit.

## 5. Operación

```bash
# Estado y memoria
sudo docker compose -f compose.oracle.yaml ps
sudo docker stats --no-stream

# Detener antes de cambios manuales o pruebas con --once
sudo docker compose -f compose.oracle.yaml stop

# Actualizar desde GitHub
git pull --ff-only
sudo docker compose -f compose.oracle.yaml build
sudo docker compose -f compose.oracle.yaml up -d
```

Si hay reinicios por memoria, revisar `docker stats` y el estado `OOMKilled` del
contenedor. Reducir primero `OCR_SCALE=1.7` y `PADDLE_DET_LIMIT_SIDE_LEN=1280`, y
recrear el contenedor. No contratar un plan pago automáticamente.

Para volver a Streamlit/Render, detener primero el worker. `app.py` y la
configuración anterior siguen en el repositorio.

## Límites conocidos

Verificación local del 1 de octubre de 2026: imagen ARM64 construida con modelos
precargados, 18 pruebas aprobadas dentro del contenedor y dependencias sin
conflictos (`pip check`). La inferencia sintética pasó bajo emulación ARM con un
hilo y MKLDNN desactivado; el perfil anterior fallaba durante la inferencia.

- Más RAM resuelve la capacidad de ejecución, pero no corrige errores de lectura.
  La factura escaneada de referencia necesita revisión de campos e importes.
- La imagen ARM debe validarse también en la VM real antes de dejarla procesando
  facturas. Una prueba local emulada no mide el rendimiento de Ampere.
- Las fechas de carga usan la zona horaria del contenedor (UTC por defecto).
- El funcionamiento en Oracle queda pendiente hasta crear la cuenta, provisionar
  la VM y configurar las credenciales. Publicar el código no crea esos recursos.
