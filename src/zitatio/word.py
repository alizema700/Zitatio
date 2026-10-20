"""Einfaches Markdown als Word-Datei (.docx) schreiben, ohne Zusatzpaket.

Für Memo und Klauselvorschläge: Überschriften (#, ##, ###), Absätze, Aufzählungen ("- "), Tabellen ("| a | b |")
und **fett** oder _kursiv_ im Text. Mehr braucht ein Memo fürs Investment Committee nicht.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape

_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_INLINE = re.compile(r"\*\*(.+?)\*\*|(?<!\w)_(.+?)_(?!\w)")


def _runs(text: str, bold: bool = False) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append((text[pos : m.start()], bold, False))
        out.append((m.group(1), True, False) if m.group(1) is not None else (m.group(2), bold, True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], bold, False))
    return "".join(f'<w:r><w:rPr>{"<w:b/>" if b else ""}{"<w:i/>" if i else ""}</w:rPr>'
                   f'<w:t xml:space="preserve">{escape(t)}</w:t></w:r>' for t, b, i in out)


def _para(text: str, style: str | None = None, bold: bool = False) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_runs(text, bold)}</w:p>"


def _table(rows: list[list[str]]) -> str:
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>']
    for n, row in enumerate(rows):
        cells = "".join(f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
                        f'<w:p><w:pPr><w:spacing w:after="0"/></w:pPr>{_runs(c, bold=n == 0)}</w:p></w:tc>' for c in row)
        out.append(f"<w:tr>{cells}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + "<w:p/>"


def markdown_to_docx(markdown: str) -> bytes:
    body, table = [], []
    for line in markdown.splitlines() + [""]:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                table.append(cells)
            continue
        if table:
            body.append(_table(table))
            table = []
        if not stripped:
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)", stripped)
        if heading:
            body.append(_para(heading.group(2), f"Heading{len(heading.group(1))}"))
        elif re.match(r"^[-*]\s+", stripped):
            body.append(_para("• " + re.sub(r"^[-*]\s+", "", stripped), "ListParagraph"))
        else:
            body.append(_para(stripped))
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1134" '
                'w:left="1417" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')

    def style(sid: str, name: str, size: int, level: int | None) -> str:
        outline = f'<w:outlineLvl w:val="{level}"/>' if level is not None else ""
        keep = "<w:keepNext/>" if level is not None else ""
        bold = "<w:b/>" if level is not None else ""
        indent = '<w:ind w:left="284" w:hanging="284"/>' if level is None else ""
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                f'<w:next w:val="Normal"/><w:qFormat/><w:pPr>{keep}<w:spacing w:before="{240 if level is not None else 0}" '
                f'w:after="120"/>{indent}{outline}</w:pPr>'
                f'<w:rPr>{bold}<w:sz w:val="{size}"/></w:rPr></w:style>')

    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {_NS}>'
              '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="21"/>'
              '<w:lang w:val="de-CH"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr>'
              '</w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
              + style("Heading1", "heading 1", 32, 0) + style("Heading2", "heading 2", 26, 1)
              + style("Heading3", "heading 3", 23, 2) + style("ListParagraph", "List Paragraph", 21, None) + "</w:styles>")
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_REL}/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_REL}/styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": document,
        "word/styles.xml": styles,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
