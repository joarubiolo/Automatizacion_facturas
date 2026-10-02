"""
INFERENCE ENGINE V10
====================
Convierte texto + layout en datos contables.

Prioridades:
1. Evidencia textual explícita.
2. Posición/zona del documento.
3. Checksum de CUIT.
4. Relaciones aritméticas.
5. Nunca inventar si la evidencia no alcanza.
"""

from __future__ import annotations

import re
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from table_analysis import read_amount_table, read_detail_table


PROVEEDORES_POR_CUIT = {
    "27329850027": "M.C Servicios",
    "20375558255": "ACHARES FRANCO EZEQUIEL",
    "23175945709": "SANCHEZ PUERTA FEDERICO JOSE",
}

ALICUOTAS_VALIDAS = (21.0, 10.5, 27.0, 5.0, 2.5, 0.0)


def campo(valor=None, confianza=0.0, origen="NO_DETECTADO", evidencia=None):
    return {
        "valor": valor,
        "confianza": round(float(confianza), 3),
        "origen": origen,
        "evidencia": evidencia or [],
    }


def normalizar_cuit(valor) -> Optional[str]:
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", str(valor))
    return digitos if len(digitos) == 11 else None


def cuit_es_valido(cuit) -> bool:
    cuit = normalizar_cuit(cuit)
    if not cuit:
        return False

    numeros = [int(x) for x in cuit]
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(numeros[i] * pesos[i] for i in range(10))
    dv = 11 - (total % 11)

    if dv == 11:
        dv = 0
    elif dv == 10:
        dv = 9

    return dv == numeros[10]


def normalizar_importe(s: str) -> Optional[float]:
    if s is None:
        return None

    t = str(s).strip()
    t = t.replace("$", "").replace(" ", "")
    t = t.replace("O", "0").replace("I", "1").replace("l", "1")
    t = re.sub(r"[^0-9,.\-]", "", t)

    if not t or t in {".", ",", "-"}:
        return None

    if "," in t:
        # Formato AR: 1.234.567,89
        partes = t.split(",")
        entero = "".join(partes[:-1]).replace(".", "")
        dec = partes[-1]
        t = entero + "." + dec
    elif t.count(".") > 1:
        partes = t.split(".")
        if len(partes[-1]) in (1, 2):
            t = "".join(partes[:-1]) + "." + partes[-1]
        else:
            t = "".join(partes)
    elif t.count(".") == 1 and len(t.rsplit(".", 1)[1]) == 3:
        # Un importe AR sin centavos puede usar el punto como separador de miles.
        t = t.replace(".", "")

    try:
        return round(float(t), 2)
    except Exception:
        return None


def normalizar_fecha(s: str) -> Optional[str]:
    if not s:
        return None

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return None


def _lineas(documento: Dict) -> List[Dict]:
    lineas = documento.get("lineas") or []
    if lineas:
        return lineas

    bruto = [
        x.strip()
        for x in documento.get("texto", "").splitlines()
        if x.strip()
    ]

    salida = []
    n = max(1, len(bruto))

    for i, txt in enumerate(bruto):
        y = i / n
        if y < .28:
            zona = "CABECERA"
        elif y < .46:
            zona = "CLIENTE"
        elif y < .75:
            zona = "DETALLE"
        elif y < .91:
            zona = "TOTALES"
        else:
            zona = "PIE"

        salida.append({
            "texto": txt,
            "zona": zona,
            "conf": .95,
            "x_rel": 0.0,
            "y_rel": y,
        })

    return salida


def _texto_zona(documento: Dict, zona: str) -> str:
    return "\n".join(
        l.get("texto", "")
        for l in _lineas(documento)
        if l.get("zona") == zona
    )


def inferir_fecha(documento: Dict) -> Dict:
    fuentes = [
        (_texto_zona(documento, "CABECERA"), 2.5),
        (documento.get("texto", ""), 1.0),
    ]

    patrones = (
        r"Fecha\s+y\s+Hora\s*:\s*(\d{2}[/-]\d{2}[/-]\d{2,4})",
        r"Fecha\s+de\s+Emisi[oó]n\s*:\s*(\d{2}[/-]\d{2}[/-]\d{2,4})",
        r"\bFecha\s*:\s*(\d{2}[/-]\d{2}[/-]\d{2,4})",
    )

    scores = defaultdict(float)
    evidencias = defaultdict(list)

    for texto, peso in fuentes:
        for patron in patrones:
            for m in re.finditer(patron, texto, re.I):
                f = normalizar_fecha(m.group(1))
                if f:
                    scores[f] += peso
                    evidencias[f].append(m.group(0))

    if not scores:
        return campo()

    mejor = max(scores, key=scores.get)
    return campo(
        mejor,
        min(.98, .75 + scores[mejor] * .05),
        "ETIQUETA+ZONA",
        evidencias[mejor],
    )


def inferir_tipo(texto: str) -> Dict:
    for patron in (
        r"\bFACTURA\s+([ABCEM])\b",
        r"\b([ABCEM])\s+FACTURA\b",
    ):
        m = re.search(patron, texto, re.I)
        if m:
            return campo(m.group(1).upper(), .97, "ETIQUETA", [m.group(0)])

    return campo()


def inferir_numero(texto: str) -> Tuple[Dict, Dict]:
    patrones = (
        r"Punto\s+de\s+Venta\s*:\s*(\d{4,5}).{0,40}?Comp\.?\s*Nro\.?\s*:\s*(\d{6,8})",
        r"Factura.{0,12}?(\d{4,5})\s*[- ]\s*(\d{6,8})",
        r"N[°ºo.]?\s*(\d{4,5})\s*[- ]+\s*(\d{6,8})",
    )

    for patron in patrones:
        m = re.search(patron, texto, re.I | re.S)
        if not m:
            continue

        pv = m.group(1)[-5:]
        # Si OCR antepone un dígito, preferimos los últimos 4/5 según patrón.
        if len(pv) > 4 and pv.startswith("8"):
            pv = pv[-4:]

        nro = m.group(2).zfill(8)

        return (
            campo(pv, .92, "FORMATO_FACTURA", [m.group(0)[:100]]),
            campo(nro, .92, "FORMATO_FACTURA", [m.group(0)[:100]]),
        )

    return campo(), campo()


def inferir_cuits(documento: Dict) -> Tuple[Dict, Dict]:
    candidatos = []

    for linea in _lineas(documento):
        txt = linea.get("texto", "")

        for m in re.finditer(
            r"(?<!\d)(\d{2}[-\s]?\d{8}[-\s]?\d)(?!\d)",
            txt,
        ):
            cuit = normalizar_cuit(m.group(1))
            if not cuit or not cuit_es_valido(cuit):
                continue

            zona = linea.get("zona")
            score = 40

            if zona == "CABECERA":
                score += 35
            elif zona == "CLIENTE":
                score += 28
            elif zona == "PIE":
                score -= 80

            if re.search(r"C\.?\s*U\.?\s*[I1]\.?\s*T", txt, re.I):
                score += 20
            elif "cuit" in txt.lower():
                score += 20

            if any(x in txt.lower() for x in (
                "tel/fax", "grafica", "gráfica", "imprenta",
                "e-mail", "gmail", "hab. municipal",
            )):
                score -= 100

            candidatos.append({
                "valor": cuit,
                "score": score,
                "zona": zona,
                "y_rel": float(linea.get("y_rel", 0)),
                "evidencia": txt,
            })

    if not candidatos:
        # Fallback texto plano
        for m in re.finditer(
            r"(?<!\d)(\d{2}[-\s]?\d{8}[-\s]?\d)(?!\d)",
            documento.get("texto", ""),
        ):
            cuit = normalizar_cuit(m.group(1))
            if cuit and cuit_es_valido(cuit):
                candidatos.append({
                    "valor": cuit,
                    "score": 35,
                    "zona": "DESCONOCIDA",
                    "y_rel": .5,
                    "evidencia": m.group(0),
                })

    if not candidatos:
        return campo(), campo()

    agrupados = defaultdict(list)
    for c in candidatos:
        agrupados[c["valor"]].append(c)

    resumidos = []

    for valor, grupo in agrupados.items():
        mejor = max(grupo, key=lambda x: x["score"])
        score = mejor["score"] + min(20, (len(grupo) - 1) * 5)

        resumidos.append({
            "valor": valor,
            "score": score,
            "zona": mejor["zona"],
            "y_rel": mejor["y_rel"],
            "evidencias": [x["evidencia"] for x in grupo[:5]],
        })

    prov = max(
        resumidos,
        key=lambda x:
            x["score"]
            + (30 if x["zona"] == "CABECERA" else 0)
            - (100 if x["zona"] == "PIE" else 0),
    )

    otros = [x for x in resumidos if x["valor"] != prov["valor"]]
    cli = None

    if otros:
        cli = max(
            otros,
            key=lambda x:
                x["score"]
                + (35 if x["zona"] == "CLIENTE" else 0)
                + (10 if x["y_rel"] > prov["y_rel"] else 0)
                - (100 if x["zona"] == "PIE" else 0),
        )

    proveedor = campo(
        prov["valor"],
        min(.99, .72 + max(0, prov["score"]) / 500),
        "POSICION+CHECKSUM",
        prov["evidencias"],
    )

    cliente = (
        campo(
            cli["valor"],
            min(.97, .68 + max(0, cli["score"]) / 500),
            "POSICION+CHECKSUM",
            cli["evidencias"],
        )
        if cli else campo()
    )

    return proveedor, cliente


def inferir_nombres(documento: Dict, cuit_proveedor: Dict, cuit_cliente: Dict):
    prov_cuit = cuit_proveedor.get("valor")

    if prov_cuit in PROVEEDORES_POR_CUIT:
        proveedor = campo(
            PROVEEDORES_POR_CUIT[prov_cuit],
            .99,
            "MAESTRO_CUIT",
            [prov_cuit],
        )
    else:
        proveedor = campo()

    texto = documento.get("texto", "")

    cliente = campo()

    patrones = (
        r"Apellido\s+y\s+Nombre\s*/\s*Raz[oó]n\s+Social\s*:\s*(.+)",
        r"^\s*Sr\.?\s*:\s*(.+?)(?:\s{2,}CUIT|$)",
    )

    for patron in patrones:
        m = re.search(patron, texto, re.I | re.M)
        if m:
            nombre = " ".join(m.group(1).split())[:120]
            if nombre:
                cliente = campo(nombre, .90, "ETIQUETA_CLIENTE", [m.group(0)])
                break

    # Posicional: nombre cercano al CUIT cliente dentro de zona CLIENTE.
    if not cliente["valor"] and cuit_cliente.get("valor"):
        lineas_cliente = [
            l for l in _lineas(documento)
            if l.get("zona") == "CLIENTE"
        ]

        candidatos = []
        for l in lineas_cliente:
            txt = l["texto"]
            if len(txt) < 3 or len(txt) > 100:
                continue
            if re.search(r"\d{7,}", txt):
                continue
            if any(k in txt.lower() for k in (
                "cuit", "iva", "responsable", "cantidad",
                "descripcion", "precio", "contado",
            )):
                continue

            letras = [c for c in txt if c.isalpha()]
            if len(letras) < 3:
                continue

            candidatos.append((
                float(l.get("conf", .5)),
                txt.strip(),
            ))

        if candidatos:
            candidatos.sort(reverse=True)
            cliente = campo(
                candidatos[0][1],
                min(.90, .70 + candidatos[0][0] * .20),
                "POSICION_CLIENTE",
                [candidatos[0][1]],
            )

    return proveedor, cliente


def _buscar_importe(texto: str, etiquetas: Tuple[str, ...]):
    patron_num = r"([0-9]+(?:[.,][0-9]+)*)(?![0-9.,])"

    for etiqueta in etiquetas:
        m = re.search(
            rf"{etiqueta}[ \t:$=]*{patron_num}",
            texto,
            re.I,
        )
        if m:
            valor = normalizar_importe(m.group(1))
            if valor is not None:
                return valor, m.group(0)

    return None, None


def _detectar_alicuotas(texto: str) -> List[float]:
    tasas = []

    for m in re.finditer(
        r"\(?\s*(\d{1,2}(?:[\.,]\d{1,2})?)\s*(?:%|\))",
        texto,
    ):
        try:
            bruto = float(m.group(1).replace(",", "."))
        except ValueError:
            continue

        for tasa in ALICUOTAS_VALIDAS:
            if abs(bruto - tasa) <= .75 and tasa not in tasas:
                tasas.append(tasa)

    return tasas


def inferir_importes(documento: Dict):
    texto = documento.get("texto", "")
    texto_totales = _texto_zona(documento, "TOTALES")
    fuente = texto_totales + "\n" + texto
    tasas = _detectar_alicuotas(fuente)
    tabla = read_amount_table(documento, normalizar_importe, tasas)
    if tabla is not None:
        return tabla

    neto, ev_neto = _buscar_importe(
        fuente,
        (
            r"Importe\s+Neto\s+Gravado\s*:?",
            r"Sub[- ]?Total\s*:?",
            r"SUBTOTAL\s*:?",
        ),
    )

    total, ev_total = _buscar_importe(
        fuente,
        (
            r"Importe\s+Total\s*:?",
            r"Total\s+General\s*:?",
            r"\bTOTAL\s*\$?\s*:?",
        ),
    )

    otros, ev_otros = _buscar_importe(
        fuente,
        (
            r"Importe\s+Otros\s+Tributos\s*:?",
            r"Percepciones\s+Otros\s*:?",
        ),
    )
    otros = float(otros or 0)

    # IVA explícito
    iva, ev_iva = _buscar_importe(
        fuente,
        (
            r"\bIVA\s+\d+(?:[\.,]\d+)?\s*%\s*:?",
            r"(?<!ALICUOTA )\bIVA\s*:?(?!\s*\d+(?:[.,]\d+)?\s*[%\)])",
        ),
    )

    # Solo completar un dato ausente cuando una unica alicuota lo respalda.
    # Un importe explicito contradictorio nunca se sobrescribe para cuadrar.
    if neto is not None and len(tasas) == 1:
        tasa = tasas[0]
        iva_estimado = round(neto * tasa / 100.0, 2)

        if iva is None:
            iva = iva_estimado
            ev_iva = f"calculado {neto} x {tasa}%"

    # Si total falta y tenemos componentes.
    if total is None and neto is not None and iva is not None:
        total = round(neto + iva + otros, 2)
        ev_total = "calculado neto + IVA + otros tributos"

    # Si solo tenemos total y alícuota, inferir neto/IVA.
    if total is not None and neto is None and iva is None and len(tasas) == 1:
        tasa = tasas[0]
        base = total - otros
        neto = round(base / (1 + tasa / 100.0), 2)
        iva = round(base - neto, 2)
        ev_neto = f"inferido desde total y alícuota {tasa}%"
        ev_iva = f"inferido desde total y alícuota {tasa}%"

    return {
        "neto": campo(
            neto,
            .94 if ev_neto and "calcul" not in str(ev_neto) and "infer" not in str(ev_neto) else (.82 if neto is not None else 0),
            "OCR_ETIQUETA" if ev_neto and "calcul" not in str(ev_neto) and "infer" not in str(ev_neto) else ("INFERENCIA_MATEMATICA" if neto is not None else "NO_DETECTADO"),
            [ev_neto] if ev_neto else [],
        ),
        "iva": campo(
            iva,
            .93 if ev_iva and "calcul" not in str(ev_iva) and "correg" not in str(ev_iva) and "infer" not in str(ev_iva) else (.84 if iva is not None else 0),
            "OCR_ETIQUETA" if ev_iva and "calcul" not in str(ev_iva) and "correg" not in str(ev_iva) and "infer" not in str(ev_iva) else ("INFERENCIA_MATEMATICA" if iva is not None else "NO_DETECTADO"),
            [ev_iva] if ev_iva else [],
        ),
        "importe_otros_tributos": campo(
            otros,
            .92 if ev_otros else .75,
            "OCR_ETIQUETA" if ev_otros else "DEFAULT_CERO",
            [ev_otros] if ev_otros else [],
        ),
        "total": campo(
            total,
            .96 if ev_total and "calcul" not in str(ev_total) else (.84 if total is not None else 0),
            "OCR_ETIQUETA" if ev_total and "calcul" not in str(ev_total) else ("INFERENCIA_MATEMATICA" if total is not None else "NO_DETECTADO"),
            [ev_total] if ev_total else [],
        ),
    }


def inferir_detalle(documento: Dict) -> Dict:
    tabla = read_detail_table(documento)
    if tabla is not None:
        return tabla
    candidatos = []

    for linea in _lineas(documento):
        if linea.get("zona") != "DETALLE":
            continue

        txt = linea.get("texto", "").strip()
        if len(txt) < 5:
            continue

        if any(k in txt.lower() for k in (
            "cantidad",
            "descripcion",
            "descripción",
            "precio unitario",
            "alicuota",
            "alícuota",
            "subtotal",
            "total",
            "recibi", "recibí", "hojas", "cuenta corriente",
            "son pesos", "c.a.i", "c.a.e", "percepciones",
        )):
            continue

        if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", txt):
            candidatos.append(txt)

    # Dedup
    unicos = []
    vistos = set()

    for x in candidatos:
        key = re.sub(r"\W+", "", x.lower())[:100]
        if key and key not in vistos:
            vistos.add(key)
            unicos.append(x)

    if not unicos:
        return campo()

    return campo(
        " | ".join(unicos[:10]),
        .80,
        "LAYOUT_DETALLE",
        unicos[:5],
    )


def inferir_cae(texto: str):
    cae = campo()
    venc = campo()

    m = re.search(
        r"(?:CAE\s+N[°ºo.]?|Numero\s+de\s+CAE|Número\s+de\s+CAE)\s*:\s*(\d{14})",
        texto,
        re.I,
    )
    if m:
        cae = campo(m.group(1), .98, "ETIQUETA", [m.group(0)])

    m = re.search(
        r"(?:Fecha\s+de\s+Vto\.?\s+de\s+CAE|Fecha\s+Vencimiento\s+CAE)\s*:\s*"
        r"(\d{2}[/-]\d{2}[/-]\d{2,4})",
        texto,
        re.I,
    )
    if m:
        fecha = normalizar_fecha(m.group(1))
        if fecha:
            venc = campo(fecha, .97, "ETIQUETA", [m.group(0)])

    return cae, venc


def inferir_factura(documento: Dict) -> Dict:
    texto = documento.get("texto", "")

    fecha = inferir_fecha(documento)
    tipo = inferir_tipo(texto)
    pv, numero = inferir_numero(texto)
    cuit_prov, cuit_cli = inferir_cuits(documento)
    proveedor, cliente = inferir_nombres(documento, cuit_prov, cuit_cli)
    importes = inferir_importes(documento)
    detalle = inferir_detalle(documento)
    cae, venc = inferir_cae(texto)

    meta = {
        "fecha_factura": fecha,
        "tipo": tipo,
        "punto_venta": pv,
        "numero": numero,
        "proveedor": proveedor,
        "cuit_proveedor": cuit_prov,
        "cliente": cliente,
        "cuit_cliente": cuit_cli,
        "detalle": detalle,
        "neto": importes["neto"],
        "iva": importes["iva"],
        "importe_otros_tributos": importes["importe_otros_tributos"],
        "total": importes["total"],
        "cae": cae,
        "vencimiento_cae": venc,
    }

    salida = {k: v["valor"] for k, v in meta.items()}
    salida["_meta"] = meta
    salida["_metodo_extraccion"] = documento.get("metodo", "")
    salida["_alertas_extraccion"] = importes.get("_alertas", [])
    salida["_campos_inferidos"] = [
        k
        for k, v in meta.items()
        if v["valor"] is not None
        and (
            "INFERENCIA" in v["origen"]
            or "POSICION" in v["origen"]
            or "MAESTRO" in v["origen"]
        )
    ]

    return salida
