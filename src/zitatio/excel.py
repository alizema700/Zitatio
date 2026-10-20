"""Prüfergebnis als Excel-Arbeitsmappe mit echten Formeln.

Deal-Teams arbeiten in Excel weiter. Die Mappe enthält die Aussagen mit Status und Beleg, und dort, wo Zitatio
rechnet (EBITDA-Brücke, Nettoverschuldung, Covenant, Closing-Liste), stehen die Rechnungen als Formeln, damit
das Team Annahmen ändern kann und die Summen mitlaufen. Geschrieben ohne Zusatzpaket (SpreadsheetML).
"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

# Zellformate in styles.xml: 0 normal, 1 fett, 2 CHF-Betrag, 3 CHF-Betrag fett, 4 Prozent, 5 Faktor "0.00x"
NORMAL, BOLD, CHF, CHF_BOLD, PERCENT, FACTOR = range(6)


class Sheet:
    def __init__(self, name: str, widths: list[int]):
        self.name = name[:31]
        self.widths = widths
        self.rows: list[list] = []

    def add(self, *cells) -> int:
        """Zeile anhängen; gibt die Excel-Zeilennummer zurück. Zelle: Wert, ("=FORMEL", Format) oder (Wert, Format)."""
        self.rows.append(list(cells))
        return len(self.rows)


def _col(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell(ref: str, cell) -> str:
    style = NORMAL
    if isinstance(cell, tuple):
        cell, style = cell
    s = f' s="{style}"' if style else ""
    if cell is None or cell == "":
        return f'<c r="{ref}"{s}/>' if style else ""
    if isinstance(cell, str) and cell.startswith("="):
        return f'<c r="{ref}"{s}><f>{escape(cell[1:])}</f></c>'
    if isinstance(cell, bool):
        return f'<c r="{ref}" t="b"{s}><v>{int(cell)}</v></c>'
    if isinstance(cell, (int, float, Decimal)):
        return f'<c r="{ref}"{s}><v>{cell}</v></c>'
    text = escape(str(cell)).replace("\n", "&#10;")
    return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(sheet: Sheet) -> str:
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(sheet.widths))
    rows = []
    for r, cells in enumerate(sheet.rows, 1):
        xml = "".join(_cell(f"{_col(c)}{r}", v) for c, v in enumerate(cells))
        rows.append(f'<row r="{r}">{xml}</row>')
    last = f"{_col(max(len(sheet.widths), 1) - 1)}{max(len(sheet.rows), 1)}"
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
            'state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData>'
            f'<autoFilter ref="A1:{last}"/></worksheet>') if sheet.name == "Aussagen" else (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData></worksheet>')


_STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0"/>'
           '<numFmt numFmtId="165" formatCode="0.0%"/><numFmt numFmtId="166" formatCode="0.00&quot;x&quot;"/></numFmts>'
           '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
           '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
           '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
           '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
           '<cellXfs count="6"><xf/>'
           '<xf fontId="1" applyFont="1"/>'
           '<xf numFmtId="164" applyNumberFormat="1"/>'
           '<xf numFmtId="164" fontId="1" applyNumberFormat="1" applyFont="1"/>'
           '<xf numFmtId="165" applyNumberFormat="1"/>'
           '<xf numFmtId="166" applyNumberFormat="1"/></cellXfs>'
           '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _workbook(sheets: list[Sheet]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1))
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   f"{overrides}</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="xl/workbook.xml"/></Relationships>')
        names = "".join(f'<sheet name="{escape(s.name)}" sheetId="{i}" r:id="rId{i}"/>' for i, s in enumerate(sheets, 1))
        defined = ('<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
                   f"Aussagen!$A$1:${_col(len(sheets[0].widths) - 1)}${max(len(sheets[0].rows), 1)}"
                   "</definedName></definedNames>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{names}</sheets>{defined}<calcPr fullCalcOnLoad="1"/></workbook>')
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            f'worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        styles_id = len(sheets) + 1
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'{rels}<Relationship Id="rId{styles_id}" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                   'Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(s))
    return out.getvalue()


def to_xlsx(run) -> bytes:
    from .render import _decision

    sheets = []
    claims = Sheet("Aussagen", [6, 22, 70, 18, 18, 60, 60, 14, 30, 14])
    claims.add(*[(h, BOLD) for h in ("Nr", "Abschnitt", "Aussage", "Fundstellen", "Status", "Begründung", "Belege",
                                      "Entscheid", "Notiz", "Prüfer")])
    for f in run.findings:
        claims.add(f.claim.number, f.claim.section, f.claim.clean_text, ", ".join(c.label for c in f.claim.citations),
                   f.status.label, " ".join(f.reasons),
                   " | ".join(f"{e.doc_label}, S. {e.page}: {e.match}" for e in f.evidence), *_decision(run, f))
    sheets.append(claims)

    if run.addbacks:
        bridge = Sheet("EBITDA-Brücke", [70, 10, 16, 18])
        bridge.add(("Posten", BOLD), ("Aussage", BOLD), ("Status", BOLD), ("Betrag CHF", BOLD))
        for c in run.addbacks:
            bridge.add((c.section, BOLD))
            base = c.expected - sum((v for _, v in c.items), Decimal(0))
            first = bridge.add("Ausgewiesenes EBITDA", c.base.claim.number, c.base.status.label, (base, CHF))
            for f, value in c.items:
                bridge.add(f.claim.clean_text, f.claim.number, f.status.label, (value, CHF))
            last = len(bridge.rows)
            total = bridge.add(("Nachgerechnet", BOLD), "", "", (f"=SUM(D{first}:D{last})", CHF_BOLD))
            stated = bridge.add("Bericht nennt", c.total.claim.number, c.total.status.label, (c.stated, CHF))
            bridge.add("Differenz", "", "", (f"=D{stated}-D{total}", CHF))
            unsupported = "+".join(f"D{first + 1 + k}" for k, (f, _) in enumerate(c.items)
                                   if any(f is u for u in c.unsupported)) or "0"
            bridge.add("davon ohne Beleg", "", "", (f"={unsupported}", CHF))
            bridge.add("Anteil Bereinigungen am bereinigten EBITDA", "", "",
                       (f"=IF(D{total}=0,0,SUM(D{first + 1}:D{last})/D{total})", PERCENT))
            bridge.add()
        sheets.append(bridge)

    nd = run.netdebt
    if nd is not None and nd.items:
        from .netdebt import AEHNLICH, EVENTUAL, FINANZ

        debt = Sheet("Nettoverschuldung", [55, 22, 30, 18])
        debt.add(("Posten", BOLD), ("Art", BOLD), ("Fundstelle", BOLD), ("Betrag CHF", BOLD))

        def item_row(i) -> int:
            return debt.add(i.label, i.kind, ", ".join(f"{e.doc_label}, S. {e.page}" for e in i.evidence),
                            (i.amount, CHF))

        fin = [item_row(i) for i in nd.items if i.kind == FINANZ]
        net = debt.add((f"Nettoverschuldung laut Bilanz {nd.year}", BOLD), "", "",
                       ("=" + "+".join(f"D{r}" for r in fin), CHF_BOLD))
        similar = [item_row(i) for i in nd.items if i.kind == AEHNLICH]
        adjusted = debt.add(("Inklusive schuldenähnlicher Posten", BOLD), "", "",
                            ("=" + "+".join(f"D{r}" for r in [net] + similar), CHF_BOLD))
        contingent = [i for i in nd.items if i.kind == EVENTUAL]
        if contingent:
            debt.add()
            debt.add(("Eventualverbindlichkeiten (nicht in der Summe)", BOLD))
            for i in contingent:
                item_row(i)
        if nd.ebitda:
            debt.add()
            ebitda = debt.add(f"EBITDA {nd.year}", "", nd.ebitda_evidence.doc_label if nd.ebitda_evidence else "",
                              (nd.ebitda, CHF))
            ratio = debt.add("Nettoverschuldung / EBITDA", "", "", (f"=IF(D{ebitda}=0,0,D{net}/D{ebitda})", FACTOR))
            debt.add("inkl. schuldenähnlicher Posten / EBITDA", "", "", (f"=IF(D{ebitda}=0,0,D{adjusted}/D{ebitda})", FACTOR))
            if nd.covenant:
                c = nd.covenant
                limit = debt.add("Covenant: höchstens", "", f"{c.evidence.doc_label}, S. {c.evidence.page}",
                                 (c.limit, FACTOR))
                debt.add(("Covenant eingehalten", BOLD), "", "", f'=IF(D{ratio}<=D{limit},"ja","nein")')
        sheets.append(debt)

    v = run.valuation
    if v is not None and v.equity is not None:
        price = Sheet("Preisbrücke", [55, 40, 18])
        price.add(("Posten", BOLD), ("Grundlage", BOLD), ("Betrag CHF", BOLD))
        ebitda = price.add("Bereinigtes EBITDA laut Bericht", "", (v.ebitda, CHF))
        multiple = price.add("Multiple", v.multiple_text[:120], (v.multiple, FACTOR))
        ev = price.add(("Unternehmenswert", BOLD), "", (f"=C{ebitda}*C{multiple}", CHF_BOLD))
        debt = price.add(f"Nettoverschuldung laut Bilanz {v.year}", "", (v.net_debt, CHF))
        equity = price.add(("Equity Value laut Rechnung", BOLD), "", (f"=C{ev}-C{debt}", CHF_BOLD))
        rows = []
        for i in v.impacts:
            if i.label.startswith("Bereinigung ohne Beleg"):
                rows.append(price.add(i.label, i.basis, (f"=-{-i.amount / v.multiple}*C{multiple}", CHF)))
            else:
                rows.append(price.add(i.label, i.basis, (i.amount, CHF)))
        if rows:
            after = price.add(("Equity Value nach Befunden", BOLD), "",
                              ("=" + "+".join(f"C{r}" for r in [equity] + rows), CHF_BOLD))
            price.add("Veränderung", "", (f"=IF(C{equity}=0,0,C{after}/C{equity}-1)", PERCENT))
        if v.risks:
            price.add()
            price.add(("Risiken daneben (nicht in der Summe)", BOLD))
            for i in v.risks:
                price.add(i.label, i.basis, (i.amount, CHF))
        sheets.append(price)

    if run.closing:
        closing = Sheet("Closing-Liste", [12, 45, 18, 80, 18])
        closing.add(*[(h, BOLD) for h in ("Index", "Vertrag", "Art", "Zu klären", "Volumen p.a. CHF")])
        first = 2
        for i in run.closing:
            volume = i.terms.volume if i.kind == "kontrollwechsel" and i.terms.volume else None
            closing.add(i.terms.doc.label, i.terms.doc.title, i.kind, i.text, (volume, CHF) if volume else "")
        last = len(closing.rows)
        closing.add()
        total = closing.add(("Volumen unter Kontrollwechselklauseln", BOLD), "", "", "",
                            (f'=SUMIF(C{first}:C{last},"kontrollwechsel",E{first}:E{last})', CHF_BOLD))
        if run.revenue:
            revenue = closing.add(f"Umsatz {run.revenue[0]}", "", "", "", (run.revenue[1], CHF))
            closing.add("Anteil am Umsatz", "", "", "", (f"=IF(E{revenue}=0,0,E{total}/E{revenue})", PERCENT))
        sheets.append(closing)

    from .questions import request_list

    questions = request_list(run)
    if questions:
        sheet = Sheet("Fragenliste", [6, 22, 10, 90, 40, 40])
        sheet.add(*[(h, BOLD) for h in ("Nr", "Bereich", "Priorität", "Frage", "Bezug", "Antwort Verkäufer")])
        for q in questions:
            sheet.add(q.number, q.area, q.priority, q.text, q.reference, "")
        sheets.append(sheet)

    room = Sheet("Datenraum", [12, 60, 10, 70])
    room.add(*[(h, BOLD) for h in ("Index", "Dokument", "Seiten", "SHA-256")])
    for d in run.room.documents:
        room.add(d.label, d.title, len(d.pages), d.sha256)
    sheets.append(room)
    return _workbook(sheets)
