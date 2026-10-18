"""Word-Dateien (.docx) ohne Zusatzpaket lesen.

Überschriften werden zu Markdown-Überschriften, Aufzählungen zu "- ",
Tabellenzeilen zu je einem Absatz ("Zelle; Zelle; …"). Manuelle
Seitenumbrüche trennen Seiten, damit Datenraum-Dokumente in Word
seitengenau zitiert werden können.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PAGE_BREAK = "\f"


def _paragraph_text(p: ET.Element) -> str:
    parts = []
    for node in p.iter():
        if node.tag == f"{W}t":
            parts.append(node.text or "")
        elif node.tag == f"{W}tab":
            parts.append(" ")
        elif node.tag in (f"{W}br", f"{W}cr"):
            parts.append(PAGE_BREAK if node.get(f"{W}type") == "page" else "\n")
    return "".join(parts)


def _heading_level(p: ET.Element) -> int | None:
    style = p.find(f"{W}pPr/{W}pStyle")
    if style is None:
        return None
    m = re.match(r"(?:heading|berschrift|titre|title)\s*(\d)?", (style.get(f"{W}val") or "").lower().lstrip("ü"))
    if not m:
        return None
    return int(m.group(1) or 1)


def _is_list(p: ET.Element) -> bool:
    return p.find(f"{W}pPr/{W}numPr") is not None


def docx_to_text(data: bytes) -> str:
    """Text eines .docx in Lesereihenfolge; Seiten mit \\f getrennt."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    lines: list[str] = []
    for block in list(body) if body is not None else []:
        if block.tag == f"{W}p":
            text = _paragraph_text(block)
            if not text.strip():
                if PAGE_BREAK in text:
                    lines.append(PAGE_BREAK)
                lines.append("")
                continue
            level = _heading_level(block)
            if level:
                lines.extend(["", "#" * min(level, 6) + " " + text.strip(), ""])
            elif _is_list(block):
                lines.append("- " + text.strip())
            else:
                lines.extend([text.strip(), ""])
        elif block.tag == f"{W}tbl":
            for row in block.iter(f"{W}tr"):
                cells = [" ".join(_paragraph_text(p).strip() for p in tc.iter(f"{W}p")).strip()
                         for tc in row.iter(f"{W}tc")]
                cells = [c for c in cells if c]
                if cells:
                    lines.extend(["; ".join(cells), ""])
    text = "\n".join(lines)
    text = re.sub(r"\n*\f\n*", "\f", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
