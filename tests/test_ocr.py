"""Texterkennung für gescannte PDF-Seiten (läuft nur, wo Tesseract installiert ist)."""

import io

import pytest

from zitatio import ocr
from zitatio.dataroom import DataRoom
from zitatio.report import parse_report
from zitatio.verify import Status, verify_claim

needs_tesseract = pytest.mark.skipif(not ocr.available(), reason="Tesseract oder pdftoppm fehlt")


def _scan(lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (1700, 2200), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for n, line in enumerate(lines):
        draw.text((120, 150 + n * 70), line, fill=0, font=font)
    out = io.BytesIO()
    image.save(out, "PDF", resolution=200)
    return out.getvalue()


@needs_tesseract
def test_scanned_register_extract_is_read_and_marked():
    room = DataRoom()
    room.add("1.1 Handelsregisterauszug.pdf", _scan(["Handelsregister des Kantons Zürich", "Firma: Muster AG",
                                                     "Aktienkapital: CHF 1'200'000", "Sitz: Zürich"]))
    doc = room.documents[0]
    assert doc.ocr == (1,) and "1'200'000" in doc.pages[0]
    assert any("per OCR gelesen" in w for w in room.warnings)
    finding = verify_claim(parse_report("Das Aktienkapital beträgt CHF 1.2 Mio. [DR 1.1, S. 1].")[0], room)
    assert finding.status is Status.GEPRUEFT and finding.evidence[0].ocr


def test_normalize_swiss_thousands():
    assert ocr.normalize("CHF 1’200‘000 und 3 ´500") == "CHF 1'200'000 und 3'500"


def test_switch_off(monkeypatch):
    monkeypatch.setenv("ZITATIO_OCR", "0")
    assert not ocr.available()
