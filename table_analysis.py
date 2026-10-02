"""Read invoice columns using their headers rather than fixed page zones.

Multiple OCR readings are candidates, not replacements for observed evidence.
Accounting identities select a supported combination; contradictions remain
visible so that validation can send the invoice to review.
"""

import itertools
import re
import unicodedata


def plain(text):
    return "".join(c for c in unicodedata.normalize("NFKD", str(text)).lower()
                   if not unicodedata.combining(c))


def _anchors(tokens, patterns):
    result = []
    for token in tokens:
        text = plain(token["texto"])
        occupied = []
        for name, pattern in patterns:
            for match in re.finditer(pattern, text):
                if any(start < match.end() and match.start() < end for start, end in occupied):
                    continue
                occupied.append(match.span())
                # A detector may join adjacent headers into one box. Estimate
                # their separate positions inside that box from character spans.
                x = token["x"] + token["w"] * (match.start() + match.end()) / (2 * max(1, len(text)))
                result.append({"name": name, "x": x, "token": token})
    return sorted(result, key=lambda item: item["x"])


MONEY_PATTERN = re.compile(r"(?<![\w])[-+]?(?:\d[\d.,]*\d|\d)(?:[.,][ODIl]{1,2})?(?![\w])")


def _numbers(token, normalize):
    text = token["texto"].strip()
    for match in MONEY_PATTERN.finditer(text):
        raw = match.group()
        if raw.endswith((".", ",")):
            continue
        # DO/OO in decimal positions are common on dot-matrix prints. Restrict
        # substitutions to that numeric suffix, never arbitrary prose.
        raw = re.sub(r"([.,])([ODIl]{1,2})$", lambda m: m[1] + m[2].translate(str.maketrans("ODIl", "0011")), raw)
        value = normalize(raw)
        if value is None:
            continue
        x = token["x"] + token["w"] * (match.start() + match.end()) / (2 * max(1, len(text)))
        yield {"value": value, "raw": raw, "x": x, "confidence": float(token.get("conf", .5)),
               "evidence": text, "motor": token.get("motor", "PDF_TEXTO")}


def _rank(candidates):
    grouped = {}
    for item in candidates:
        value = item["value"]
        group = grouped.setdefault(value, {**item, "readings": [], "score": 0})
        group["readings"].append(item)
        group["score"] = max(group["score"], item["confidence"])
        group["confidence"] = max(group["confidence"], item["confidence"])
    for group in grouped.values():
        motors = {item["motor"] for item in group["readings"]}
        group["score"] += min(.12, (len(group["readings"]) - 1) * .025) + (len(motors) - 1) * .08
    return sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:8]


def read_amount_table(document, normalize, rates):
    lines = document.get("lineas") or []
    candidates = {name: [] for name in ("neto", "iva", "total", "importe_otros_tributos")}
    found_table = False
    for header in lines:
        text = plain(header["texto"])
        if not re.search(r"sub\s*total|neto", text) or "iva" not in text:
            continue
        patterns = (
            ("rate", r"alicuota\s*(?:i[vun]a)?"),
            ("other", r"percep\w*\s*(?:otros|i[vun]a)?|otros\s+tributos"),
            ("non_taxed", r"conceptos\s+no\s+grav\w*|no\s+grav\w*"),
            ("neto", r"sub\s*total|(?:importe\s+)?neto(?:\s+gravado)?"),
            ("iva", r"\bi[vun]a\b"),
        )
        columns = _anchors(header.get("tokens", []), patterns)
        # Repeated passes can recover a header missing from the principal OCR.
        height = max((t["h"] for t in header.get("tokens", [])), default=1)
        top = min((t["y"] for t in header.get("tokens", [])), default=0)
        variants = {}
        for token in document.get("ocr_alternativas", []):
            if token.get("pagina", 1) == header.get("pagina", 1) and abs(token["y"] - top) < height:
                variants.setdefault(token.get("lectura", token.get("motor")), []).append(token)
        for tokens in variants.values():
            alternative = _anchors(tokens, patterns)
            if {"neto", "iva"}.issubset({col["name"] for col in alternative}):
                if not {"neto", "iva"}.issubset({col["name"] for col in columns}):
                    columns = alternative
        if not {"neto", "iva"}.issubset({col["name"] for col in columns}):
            if len(columns) >= 3:
                found_table = True  # Partial table: request review, not text-based inference.
            continue
        found_table = True
        page = header.get("pagina", 1)
        bottom = max(t["y"] + t["h"] for t in header["tokens"])
        height = max(t["h"] for t in header["tokens"])
        # Stop at the next TOTAL row instead of accidentally including payment,
        # receipt, authorization or page numbers below the table.
        stops = [min(t["y"] for t in line["tokens"])
                 for line in lines if line.get("pagina", 1) == page
                 and line.get("tokens") and re.search(r"\btotal\b", plain(line["texto"]))
                 and min(t["y"] for t in line["tokens"]) > bottom]
        stop = min(stops) if stops else bottom + height * 4
        source = document.get("tokens", []) + document.get("ocr_alternativas", [])
        numeric_rows = {}
        for token in source:
            if token.get("pagina", 1) != page:
                continue
            cy = token["y"] + token["h"] / 2
            if not bottom < cy < stop:
                continue
            for number in _numbers(token, normalize):
                column = min(columns, key=lambda col: abs(col["x"] - number["x"]))
                if column["name"] not in {"neto", "iva", "other"}:
                    continue
                if number["value"] < 0:
                    continue
                # Keep tax rows separate so invoices with multiple VAT rates
                # sum their printed amounts instead of applying the first rate.
                row = next((key for key in numeric_rows if abs(key - cy) < height * .65), cy)
                numeric_rows.setdefault(row, {}).setdefault(column["x"], []).append(number)
        per_field = {"neto": [], "iva": [], "importe_otros_tributos": []}
        for name in per_field:
            column_name = "other" if name == "importe_otros_tributos" else name
            cells = [_rank(row.get(col["x"], [])) for row in numeric_rows.values()
                     for col in columns if col["name"] == column_name and row.get(col["x"])]
            if cells:
                # Bound work for long summaries while preserving alternatives
                # in ordinary one/two-rate invoices.
                sums = [{"value": 0, "score": 0, "confidence": 1, "readings": []}]
                for cell in cells:
                    sums = [{"value": round(a["value"] + b["value"], 2),
                             "score": a["score"] + b["score"],
                             "confidence": min(a["confidence"], b["confidence"]),
                             "readings": a["readings"] + b["readings"]}
                            for a in sums for b in cell]
                    sums = sorted(sums, key=lambda a: a["score"], reverse=True)[:32]
                per_field[name] = sums
        for name, options in per_field.items():
            candidates[name].extend(options)

    if not found_table:
        return None

    item_totals = _item_net_candidates(document, normalize)
    candidates["neto"].extend(item_totals)

    # TOTAL and an explicit payment amount provide independent readings of
    # the grand total. A repeated number elsewhere is not automatically a total.
    for line in lines:
        if not re.search(r"\btotal\b|cuenta\s+corriente|[cq]u?enta\s+corrient", plain(line["texto"])):
            continue
        if "subtotal" in plain(line["texto"]).replace(" ", ""):
            continue
        tokens = line.get("tokens", [])
        labels = _anchors(tokens, (("total", r"\btotal\b|cuenta\s+corriente|[cq]u?enta\s+corrient"),))
        if not labels:
            continue
        label = labels[0]
        for token in tokens:
            for number in _numbers(token, normalize):
                if number["x"] > label["x"] and number["value"] > 0:
                    candidates["total"].append(number)

    for token in document.get("tokens", []) + document.get("ocr_alternativas", []):
        word_total = _total_in_words(token["texto"])
        if word_total is not None:
            candidates["total"].append({"value": word_total, "confidence": token.get("conf", .7),
                                        "motor": token.get("motor", "OCR"), "evidence": token["texto"],
                                        "origin": "OCR_TOTAL_EN_LETRAS"})

    choices = {}
    for name, items in candidates.items():
        if name == "total":
            choices[name] = _rank(items)
        else:
            unique = {}
            for item in items:
                if item["value"] not in unique or unique[item["value"]]["score"] < item["score"]:
                    unique[item["value"]] = item
            choices[name] = sorted(unique.values(), key=lambda item: item["score"], reverse=True)[:16]
    if not choices["importe_otros_tributos"]:
        choices["importe_otros_tributos"] = [{"value": 0.0, "score": .7, "confidence": .7, "readings": []}]

    names = ("neto", "iva", "importe_otros_tributos", "total")
    consistent = []
    if all(choices[name] for name in names):
        for combination in itertools.product(*(choices[name] for name in names)):
            net, vat, other, total = [candidate["value"] for candidate in combination]
            sum_difference = round(abs(net + vat + other - total), 2)
            rate_difference = round(abs(round(net * rates[0] / 100, 2) - vat), 2) if len(rates) == 1 else 0
            if sum_difference > .02:
                continue
            if rate_difference > .02:
                continue
            # Cent-level exact agreement takes precedence over recognition
            # scores, which can be very high even for a misread decimal digit.
            consistent.append(((-sum_difference, -rate_difference,
                                sum(candidate["score"] for candidate in combination)), combination))
    selected = max(consistent, key=lambda item: item[0])[1] if consistent else tuple(
        next((item for item in choices[name] if item.get("origin") != "INFERENCIA_ITEMS"), None)
        for name in names)
    fields = {}
    for name, candidate in zip(names, selected):
        readings = candidate.get("readings", [candidate]) if candidate else []
        fields[name] = {
            "valor": candidate["value"] if candidate else None,
            "confianza": round(min(.97, candidate["confidence"] + (.12 if consistent else 0)), 3) if candidate else 0,
            "origen": candidate.get("origin", "OCR_COLUMNAS_VALIDADO" if consistent else "OCR_COLUMNAS") if candidate else "NO_DETECTADO",
            "evidencia": list(dict.fromkeys(item["evidence"] for item in readings)),
        }
    fields["_alertas"] = [] if consistent else ["No hay una lectura de las columnas que concilie Neto + IVA + Otros con Total y alicuota"]
    return fields


def _item_net_candidates(document, normalize):
    """A subtotal candidate backed by printed quantities and unit prices.

    It is eligible only when there is no discount column and a later match
    against VAT and the grand total confirms it. It never replaces a conflicting
    printed amount by itself.
    """
    results = []
    lines = document.get("lineas", [])
    for i, header in enumerate(lines):
        text = plain(header["texto"])
        if not ("cantidad" in text and "precio unitario" in text):
            continue
        if re.search(r"bonif|descuento", text):
            continue
        anchors = _anchors(header["tokens"], (("quantity", r"cantidad"), ("price", r"precio\s+unitario"),
                                              ("rate", r"alicuota\s*iva"), ("description", r"descripcion")))
        qty_col = next((a for a in anchors if a["name"] == "quantity"), None)
        price_col = next((a for a in anchors if a["name"] == "price"), None)
        if not qty_col or not price_col:
            continue
        height = max(t["h"] for t in header["tokens"])
        row_choices = []
        incomplete = False
        for row in lines[i + 1:]:
            if row.get("pagina", 1) != header.get("pagina", 1):
                break
            if re.search(r"sub\s*total|son.*hojas|recibi", plain(row["texto"])):
                break
            tokens = row.get("tokens", [])
            if not tokens:
                continue
            quantities = [n for t in tokens for n in _numbers(t, normalize)
                          if t["x"] < qty_col["token"]["x"] + qty_col["token"]["w"] + height]
            if not quantities:
                continue
            quantity = quantities[0]
            try:
                # Quantity columns use decimal precision (1.000 means one),
                # unlike monetary grouping (1.000 pesos means one thousand).
                quantity["value"] = float(quantity["raw"].replace(",", "."))
            except ValueError:
                incomplete = True
                break
            cy = sum(t["y"] + t["h"] / 2 for t in tokens) / len(tokens)
            price_tokens = tokens + [t for t in document.get("ocr_alternativas", [])
                                     if t.get("lectura") == "NUMERIC_DETAIL"
                                     and t.get("pagina", 1) == row.get("pagina", 1)
                                     and abs(t["y"] + t["h"] / 2 - cy) < height]
            prices = []
            for t in price_tokens:
                for number in _numbers(t, normalize):
                    nearest = min(anchors, key=lambda a: abs(a["x"] - number["x"]))
                    if nearest["name"] == "price":
                        prices.append(number)
            options = _rank(prices)
            if not options:
                incomplete = True
                break
            row_choices.append([{"value": round(quantity["value"] * p["value"], 2),
                                 "confidence": min(quantity["confidence"], p["confidence"]),
                                 "evidence": f"{quantity['evidence']} x {p['evidence']}",
                                 "motor": p["motor"]} for p in options])
        if incomplete or not row_choices:
            continue
        sums = [{"value": 0, "score": 0, "confidence": 1, "readings": []}]
        for options in row_choices:
            sums = [{"value": round(a["value"] + b["value"], 2), "score": min(a["confidence"], b["confidence"]),
                     "confidence": min(a["confidence"], b["confidence"]), "readings": a["readings"] + [b],
                     "origin": "INFERENCIA_ITEMS"} for a in sums for b in options]
            sums = sorted(sums, key=lambda a: a["score"], reverse=True)[:32]
        results.extend(sums)
    return results


def _total_in_words(text):
    text = plain(text)
    match = re.search(r"son\s+pesos\s+(.+)", text)
    if not match:
        return None
    words = re.findall(r"[a-z]+|\d+/100", match[1])
    amounts = {"cero": 0, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3,
               "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
               "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
               "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
               "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintidos": 22,
               "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
               "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
               "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
               "noventa": 90, "cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300,
               "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600, "setecientos": 700,
               "ochocientos": 800, "novecientos": 900}
    total, group, cents, cents_complete = 0, 0, None, False
    for word in words:
        word = re.sub(r"^venti", "veinti", word)
        if word in amounts:
            group += amounts[word]
        elif word == "y":
            continue
        elif word == "mil":
            total += (group or 1) * 1000
            group = 0
        elif word in {"millon", "millones"}:
            total = (total + group) * 1000000
            group = 0
        elif word == "con":
            cents = 0
            total += group
            group = 0
        elif word == "centavos" and cents is not None:
            cents = group
            group = 0
            cents_complete = True
        elif re.fullmatch(r"\d+/100", word) and cents is not None:
            cents = int(word.split("/")[0])
            cents_complete = True
        else:
            return None
    if cents is not None:
        if group or cents > 99 or not cents_complete:
            return None
        return round(total + cents / 100, 2)
    return float(total + group)


def read_detail_table(document):
    lines = document.get("lineas") or []
    details = []
    confidence = []
    for i, header in enumerate(lines):
        text = plain(header["texto"])
        if not re.search(r"descripcion|concepto|detalle", text) or not re.search(r"cantidad|precio|importe", text):
            continue
        tokens = header.get("tokens", [])
        if not tokens:
            continue
        price = _anchors(tokens, (("price", r"precio\s+unitario|importe|p\.\s*unit"),))
        right = min((a["token"]["x"] for a in price), default=float("inf"))
        left = min(t["x"] for t in tokens)
        page = header.get("pagina", 1)
        height = max(t["h"] for t in tokens)
        last_y = None
        for line in lines[i + 1:]:
            if line.get("pagina", 1) != page:
                break
            text = plain(line["texto"])
            if re.search(r"^\s*(?:sub\s*total|importe\s+neto|total\s*[:$\d]|son\s+\d+\s+hojas|recibi|c\.a\.[ei]|ca[ei]\b)", text):
                break
            row = line.get("tokens", [])
            if not row:
                continue
            y = min(t["y"] for t in row)
            selected = [t for t in row if left - height <= t["x"] < right
                        and re.search(r"[a-z]{2,}", plain(t["texto"]))]
            if not selected:
                continue
            has_numbers = any(re.search(r"\d[.,]\d", t["texto"]) for t in row)
            if not has_numbers and (last_y is None or y - last_y > height * 3):
                continue  # Do not interpret a watermark in an empty area as an item.
            description = " ".join(t["texto"] for t in selected)
            description = re.sub(r"^\d+[.,]\d{2,4}\s+", "", description)
            description = re.sub(r"\(\s*\)", "", description).strip()
            if description:
                if not has_numbers and details:
                    details[-1] += " " + description
                else:
                    details.append(description)
                confidence.extend(t.get("conf", .5) for t in selected)
                last_y = y
    if not details:
        return None
    return {"valor": " | ".join(details), "confianza": round(min(confidence), 3),
            "origen": "COLUMNAS_DESCRIPCION", "evidencia": details}
