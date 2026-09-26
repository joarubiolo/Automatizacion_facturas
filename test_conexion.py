"""
PRIMER ARCHIVO QUE TE RECOMIENDO EJECUTAR.

Sirve para comprobar:
1) que service_account.json funciona;
2) que Python ve la carpeta 01_ENTRADA;
3) que Python puede abrir Google Sheets.

Ejecutar desde la terminal:
    python test_conexion.py

Si todo está bien debería mostrar algo como:

    CONEXIÓN CORRECTA
    Sheet: Registro de Facturas
    Pestaña: FACTURAS
    Archivos en 01_ENTRADA: 1
"""

from google_services import comprobar_conexion


try:
    datos = comprobar_conexion()

    print("\n==============================")
    print("CONEXIÓN CORRECTA")
    print("==============================")
    print(f"Sheet: {datos['sheet']}")
    print(f"Pestaña: {datos['worksheet']}")
    print(f"Archivos en 01_ENTRADA: {datos['archivos_entrada']}")
    print("==============================\n")

except Exception as exc:
    print("\n==============================")
    print("ERROR DE CONEXIÓN")
    print("==============================")
    print(exc)
    print("\nRevisá:")
    print("1. Los IDs dentro de config.py")
    print("2. credentials/service_account.json")
    print("3. Que la carpeta de Drive esté compartida con la Service Account")
    print("4. Que el Google Sheet esté compartido con la Service Account")
    print("5. Que Drive API y Sheets API estén habilitadas")
    print("==============================\n")
