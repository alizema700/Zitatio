"""Excel-Dateien (.xlsx) ohne Zusatzpaket lesen.

Jedes Tabellenblatt wird zu einer Seite: "[DR 2.2, S. 3]" zitiert das dritte
Blatt. Jede Zeile wird zu "Zelle; Zelle; …". Zahlen werden so geschrieben,
wie Excel sie anzeigt: Datumszellen als 31.12.2025, Prozentzellen als 12.4 %,
Währungsformate mit Währung, sonst mit Schweizer Tausendertrennung.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_BUILTIN_DATES = set(range(14, 23)) | {45, 46, 47}
_BUILTIN_CODES = {1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 9: "0%", 10: "0.00%",
                  37: "#,##0", 38: "#,##0", 39: "#,##0.00", 40: "#,##0.00"}


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.iter(f"{M}t"))


def _formats(styles: ET.Element | None) -> list[tuple[int, str]]:
    """Je Zellstil: (numFmtId, Formatcode)."""
    if styles is None:
        return []
    custom = {int(n.get("numFmtId")): n.get("formatCode", "") for n in styles.iter(f"{M}numFmt")}
    xfs = styles.find(f"{M}cellXfs")
    out = []
    for xf in list(xfs) if xfs is not None else []:
        fid = int(xf.get("numFmtId", "0"))
        out.append((fid, custom.get(fid, _BUILTIN_CODES.get(fid, ""))))
    return out


def _is_date(fid: int, code: str) -> bool:
    if fid in _BUILTIN_DATES:
        return True
    bare = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code).lower()
    return bool(re.search(r"[dmy]", bare)) and not re.search(r"[0#]", bare)


def _decimals(code: str) -> int | None:
    m = re.search(r"0\.(0+)", code)
    return len(m.group(1)) if m else (0 if re.search(r"[0#]", code) else None)


def _group(value: Decimal, decimals: int | None, grouped: bool = True) -> str:
    if decimals is None:  # Standardformat: so viele Stellen wie nötig, ohne Tausendertrennung
        return f"{round(value, 9).normalize():f}"  # Gleitkommareste wie 0.30000000000000004
    q = value.quantize(Decimal(1).scaleb(-decimals))
    sign = "-" if q < 0 else ""
    whole, _, frac = f"{abs(q):f}".partition(".")
    whole = f"{int(whole):,}".replace(",", "'") if grouped else whole
    return sign + whole + (f".{frac}" if frac else "")


def _number(raw: str, fid: int, code: str, date1904: bool) -> str:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return raw
    if _is_date(fid, code):
        base = dt.date(1904, 1, 1) if date1904 else dt.date(1899, 12, 30)
        return (base + dt.timedelta(days=int(value))).strftime("%d.%m.%Y")
    if "%" in code:
        return _group(value * 100, _decimals(code.replace("%", "")) or 0, grouped=False) + " %"
    text = _group(value, _decimals(code) if code else None, grouped="," in code)
    cur = re.search(r"CHF|EUR|USD|€|\$", code)
    return f"{cur.group(0)} {text}" if cur else text


def _sheet_targets(z: zipfile.ZipFile, workbook: ET.Element) -> list[tuple[str, str]]:
    rels = _xml(z, "xl/_rels/workbook.xml.rels")
    targets = {r.get("Id"): r.get("Target", "") for r in (rels.iter(f"{PR}Relationship") if rels is not None else [])}
    out = []
    for sheet in workbook.iter(f"{M}sheet"):
        target = targets.get(sheet.get(f"{R}id"), "")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        out.append((sheet.get("name", ""), path))
    return out


def xlsx_to_pages(data: bytes) -> list[str]:
    """Ein Text je Tabellenblatt, erste Zeile ist der Blattname."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        workbook = _xml(z, "xl/workbook.xml")
        if workbook is None:
            return []
        pr = workbook.find(f"{M}workbookPr")
        date1904 = pr is not None and pr.get("date1904") in ("1", "true")
        shared_root = _xml(z, "xl/sharedStrings.xml")
        shared = [_text(si) for si in shared_root.iter(f"{M}si")] if shared_root is not None else []
        formats = _formats(_xml(z, "xl/styles.xml"))
        pages = []
        for name, path in _sheet_targets(z, workbook):
            sheet = _xml(z, path)
            lines = [f"Blatt: {name}"]
            for row in sheet.iter(f"{M}row") if sheet is not None else []:
                cells = []
                for c in row.iter(f"{M}c"):
                    kind, v = c.get("t", "n"), c.find(f"{M}v")
                    if kind == "s" and v is not None:
                        text = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                    elif kind == "inlineStr":
                        text = _text(c)
                    elif kind in ("str", "e") or v is None:
                        text = v.text if v is not None and v.text else ""
                    elif kind == "b":
                        text = "WAHR" if v.text == "1" else "FALSCH"
                    else:
                        style = int(c.get("s", "0"))
                        fid, code = formats[style] if style < len(formats) else (0, "")
                        text = _number(v.text or "", fid, code, date1904)
                    if text.strip():
                        cells.append(text.strip())
                if cells:
                    lines.append("; ".join(cells))
            pages.append("\n".join(lines))
        return pages
