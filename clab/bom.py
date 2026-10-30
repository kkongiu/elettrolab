import csv
import html
import io
import math

from .units import fmt, to_float


VALUE_UNITS = {"R": "\u03a9", "C": "F", "L": "H", "V": "V"}


def _value(part):
    key = {"R": "r", "C": "c", "L": "l", "V": "v"}.get(part.kind)
    unit = VALUE_UNITS.get(part.kind)
    if key and key in part.params:
        try:
            return fmt(part.num(key), unit)
        except (KeyError, TypeError, ValueError):
            pass
    return ""


def _price(part):
    raw = part.get("unit_cost", part.spec.unit_cost)
    if raw is None:
        return None
    try:
        amount = to_float(raw)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


def build_bom(doc):
    """Group physical parts by type, value, footprint and available unit price."""
    groups = {}
    for ref in sorted(doc.parts):
        part = doc.part(ref)
        if part.kind == "GND" or part.get("simulation_only", False):
            continue
        value = _value(part)
        footprint = part.get("footprint") or part.spec.footprint or ""
        currency = str(part.get("currency", part.spec.currency or "EUR")).upper()
        price = _price(part)
        key = (part.type, value, footprint, currency, price)
        if key not in groups:
            groups[key] = {
                "type": part.type,
                "name": part.name,
                "value": value,
                "footprint": footprint,
                "currency": currency,
                "unit_cost": price,
                "refs": [],
            }
        groups[key]["refs"].append(ref)

    rows = []
    totals = {}
    unpriced_qty = 0
    for row in groups.values():
        row["quantity"] = len(row["refs"])
        row["references"] = ", ".join(row.pop("refs"))
        if row["unit_cost"] is None:
            row["subtotal"] = None
            unpriced_qty += row["quantity"]
        else:
            row["subtotal"] = row["unit_cost"] * row["quantity"]
            totals[row["currency"]] = totals.get(row["currency"], 0.0) + row["subtotal"]
        rows.append(row)
    rows.sort(key=lambda row: (row["name"].casefold(), row["value"], row["references"]))
    return rows, totals, unpriced_qty


def money(amount, currency="EUR"):
    if amount is None:
        return "—"
    return f"{amount:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")


def to_html(doc, rows=None, totals=None, unpriced_qty=None):
    if rows is None:
        rows, totals, unpriced_qty = build_bom(doc)
    title = html.escape(doc.meta.get("title") or doc.meta.get("id", "Lista componenti"))
    headings = ("Qtà", "Componente", "Valore", "Riferimenti", "Footprint",
                "Prezzo unitario", "Subtotale")
    out = ["<!doctype html><html lang='it'><head><meta charset='utf-8'>",
           f"<title>Lista componenti — {title}</title>",
           "<style>body{font:14px Arial,sans-serif;color:#172033;margin:2rem}"
           "h1{font-size:1.5rem}table{border-collapse:collapse;width:100%;margin-top:1.5rem}"
           "th,td{border:1px solid #aeb8c8;padding:.55rem;text-align:left}"
           "th{background:#eef2f8}.num{text-align:right;white-space:nowrap}"
           ".summary{margin-top:1.5rem}.print{margin-bottom:1rem}"
           "@media print{body{margin:0}.print{display:none}thead{display:table-header-group}}</style>",
           "</head><body>",
           "<button class='print' onclick='window.print()'>Stampa / Salva PDF</button>",
           f"<h1>Lista componenti — {title}</h1>",
           "<table><thead><tr>"]
    out.extend(f"<th>{heading}</th>" for heading in headings)
    out.append("</tr></thead><tbody>")
    for row in rows:
        cells = (row["quantity"], row["name"], row["value"], row["references"],
                 row["footprint"], money(row["unit_cost"], row["currency"]),
                 money(row["subtotal"], row["currency"]))
        out.append("<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in cells) + "</tr>")
    out.append("</tbody></table><div class='summary'><strong>Totali prezzi noti</strong><ul>")
    if totals:
        out.extend(f"<li>{html.escape(currency)}: {money(amount, currency)}</li>"
                   for currency, amount in sorted(totals.items()))
    else:
        out.append("<li>Nessun prezzo disponibile</li>")
    out.append("</ul>")
    if unpriced_qty:
        out.append(f"<p>{unpriced_qty} componenti senza prezzo inserito; i totali sono parziali.</p>")
    out.append("</div></body></html>")
    return "\n".join(out)


def to_csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(("Quantita", "Componente", "Valore", "Riferimenti", "Footprint",
                     "Prezzo unitario", "Subtotale", "Valuta"))
    for row in rows:
        writer.writerow((row["quantity"], row["name"], row["value"], row["references"],
                         row["footprint"], row["unit_cost"] if row["unit_cost"] is not None else "",
                         row["subtotal"] if row["subtotal"] is not None else "", row["currency"]))
    return stream.getvalue()
