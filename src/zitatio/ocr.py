"""Texterkennung (OCR) für gescannte PDF-Seiten, lokal mit Tesseract.

Handelsregisterauszüge, unterschriebene Verträge und Protokolle liegen im Datenraum oft nur als Scan. Ohne Textebene
kann Zitatio dort nichts prüfen. Ist Tesseract installiert (mit den Sprachen deu, fra, ita), liest Zitatio solche
Seiten selbst: pdftoppm macht ein Bild der Seite, Tesseract den Text. Alles läuft auf dem eigenen Rechner; kein
Dokument verlässt ihn.

OCR verwechselt Zeichen. Zitatio meldet jede so gelesene Seite, und eine Fundstelle auf einer OCR-Seite trägt den
Vermerk «OCR», damit die prüfende Person den Wert am Original nachsieht. ZITATIO_OCR=0 schaltet die Texterkennung ab.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_LANGS = ("deu", "fra", "ita", "eng")
# Tesseract liest den Schweizer Tausenderapostroph oft als ’ ‘ ´ ` oder als Komma mit Leerschlag
_THOUSANDS = re.compile(r"(?<=\d)\s?[’‘´`]\s?(?=\d{3}\b)")


def available() -> bool:
    if os.environ.get("ZITATIO_OCR", "1") == "0":
        return False
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _languages() -> str:
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return "eng"
    have = set(out.split())
    return "+".join(lang for lang in _LANGS if lang in have) or "eng"


def normalize(text: str) -> str:
    return _THOUSANDS.sub("'", text)


def ocr_pdf_pages(data: bytes, pages: list[int], dpi: int = 300) -> dict[int, str]:
    """Text der angegebenen Seiten (1-basiert); Seiten, die nicht gelesen werden konnten, fehlen im Ergebnis."""
    if not pages or not available():
        return {}
    langs = _languages()
    out: dict[int, str] = {}
    with tempfile.TemporaryDirectory(prefix="zitatio-ocr-") as tmp:
        pdf = Path(tmp) / "scan.pdf"
        pdf.write_bytes(data)
        for p in pages:
            stem = Path(tmp) / f"seite-{p}"
            try:
                subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-gray", "-png", "-singlefile",
                                str(pdf), str(stem)], check=True, capture_output=True, timeout=120)
                result = subprocess.run(["tesseract", f"{stem}.png", "stdout", "-l", langs, "--psm", "6"],
                                        check=True, capture_output=True, text=True, timeout=300)
            except (OSError, subprocess.SubprocessError):
                continue
            text = normalize(result.stdout).strip()
            if text:
                out[p] = text
    return out
