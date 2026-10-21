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


def _pages_with_images(pdf: Path) -> set[int] | None:
    """Seiten mit eingebettetem Bild (ein Scan hat immer eines); None, wenn pdfimages fehlt."""
    if not shutil.which("pdfimages"):
        return None
    try:
        out = subprocess.run(["pdfimages", "-list", str(pdf)], capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pages = set()
    for line in out.splitlines()[2:]:  # zwei Kopfzeilen
        first = line.split()[:1]
        if first and first[0].isdigit():
            pages.add(int(first[0]))
    return pages


def _ocr_page(pdf: Path, p: int, dpi: int, langs: str) -> str:
    stem = pdf.with_name(f"seite-{p}")
    try:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(p), "-l", str(p), "-gray", "-png", "-singlefile",
                        str(pdf), str(stem)], check=True, capture_output=True, timeout=120)
        result = subprocess.run(["tesseract", f"{stem}.png", "stdout", "-l", langs, "--psm", "6"], check=True,
                                capture_output=True, text=True, timeout=300,
                                env={**os.environ, "OMP_THREAD_LIMIT": "1"})  # parallel über Seiten statt Threads
    except (OSError, subprocess.SubprocessError):
        return ""
    return normalize(result.stdout).strip()


def ocr_pdf_pages(data: bytes, pages: list[int], dpi: int = 300) -> dict[int, str]:
    """Text der angegebenen Seiten (1-basiert); Seiten, die nicht gelesen werden konnten, fehlen im Ergebnis.

    Gelesen werden nur Seiten mit einem Bild: Leere Trennseiten und Grafiken ohne Bild haben keinen Text zu bieten.
    Die Seiten laufen parallel auf allen Kernen."""
    from concurrent.futures import ThreadPoolExecutor

    if not pages or not available():
        return {}
    langs = _languages()
    with tempfile.TemporaryDirectory(prefix="zitatio-ocr-") as tmp:
        pdf = Path(tmp) / "scan.pdf"
        pdf.write_bytes(data)
        scanned = _pages_with_images(pdf)
        todo = [p for p in pages if scanned is None or p in scanned]
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() or 1)) as pool:
            texts = list(pool.map(lambda p: _ocr_page(pdf, p, dpi, langs), todo))
    return {p: text for p, text in zip(todo, texts) if text}
