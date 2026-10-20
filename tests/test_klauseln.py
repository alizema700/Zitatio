"""Klauselvorschläge für den Kaufvertrag."""

import io
import zipfile
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.docx import docx_to_text
from zitatio.markup import drafts, to_docx, to_markdown
from zitatio.pipeline import run_check
from zitatio.render import to_html, to_json
from zitatio.report import load_report

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def _run(with_spa: bool):
    text, data = load_report(GROSS / "dd-bericht.md")
    spa = ("spa-entwurf.md", (GROSS / "spa-entwurf.md").read_text(encoding="utf-8")) if with_spa else None
    return run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"), spa=spa)


def test_clause_drafts_follow_the_findings():
    run = _run(True)
    items = drafts(run)
    by_heading = {d.heading: d for d in items}
    coc = by_heading["Zustimmungen zum Kontrollwechsel"]
    assert coc.group == "Vollzugsbedingungen" and coc.text.count("DR 5.") == 5 and "DR 6.1" in coc.text
    # Steuern deckt Ziff. 6.1 schon: keine eigene Freistellung; neue Ziffern folgen auf 6.2
    assert "Umsatzabstimmung 2025" not in by_heading and "Steuerprüfung" not in by_heading
    klage = by_heading["Verfahren DR 10.1"]
    assert klage.number == "6.3" and "Sperrkonto" in klage.text and "CHF 1'450'000" in klage.text
    # Der Protokolleintrag zum selben Rechtsstreit gibt keine zweite Freistellung
    assert sum(d.group == "Spezifische Freistellungen" for d in items) == 1
    assert by_heading["Indirekte Teilliquidation"].number == "6.4"
    assert "Nachtrag Nr. 1 zu DR 4.1.2" in by_heading["Nachzureichende Unterlagen"].text
    assert "Leasing DR 6.2" in by_heading["Schuldenähnliche Posten"].text

    md = to_markdown(items, run.spa_name)
    assert md.startswith("# Klauselvorschläge zu spa-entwurf.md") and "**6.3 Verfahren DR 10.1**" in md
    word = to_docx(items, run.spa_name)
    with zipfile.ZipFile(io.BytesIO(word)) as z:
        assert {"word/document.xml", "word/styles.xml", "[Content_Types].xml"} <= set(z.namelist())
    assert "Indirekte Teilliquidation" in docx_to_text(word)
    assert 'id="klauseln"' in to_html(run) and '"klauseln"' in to_json(run)


def test_without_spa_every_risk_gets_an_indemnity():
    items = drafts(_run(False))
    heads = {d.heading for d in items if d.group == "Spezifische Freistellungen"}
    assert {"Steuerprüfung", "Umsatzabstimmung 2025", "Verfahren DR 10.1"} <= heads
    assert all(d.number == "" for d in items)


def test_spa_is_checked_against_share_register_statutes_and_price():
    run = _run(True)
    titles = {f.title: f for f in run.flags if f.area == "Kaufvertrag"}
    shares = titles["Verkauft werden 12'000 Aktien, die Verkäuferin hält 7'200"]
    assert "Luca Fässler (2'400 Aktien)" in shares.text and shares.docs == ["1.3"]
    assert "Zustimmung des Verwaltungsrats zur Übertragung fehlt im Vertrag" in titles
    assert any(t.startswith("Kaufpreis CHF 40'820'000 über dem geprüften Equity Value") for t in titles)
    consent = next(d for d in drafts(run) if d.heading == "Zustimmung des Verwaltungsrats")
    assert consent.number == "4.2" and "685a" in consent.text


def test_spa_without_findings():
    from zitatio.kaufvertrag import check_spa

    room = DataRoom()
    room.add("1.2 Statuten.txt", "Art. 5: Die Übertragung von Namenaktien bedarf der Zustimmung des Verwaltungsrats.".encode())
    room.add("1.3 Aktienbuch.txt", "Aktienbuch\nAlpha Holding AG: 1'000 Namenaktien (100 %)\n".encode())
    spa = ("zwischen Alpha Holding AG, Bern (die „Verkäuferin“) und Beta AG (die „Käuferin“). Die Verkäuferin verkauft "
           "1'000 Namenaktien. Vollzugsbedingung ist die Zustimmung des Verwaltungsrats zur Übertragung.")
    assert {f.level for f in check_spa("spa.md", spa, room)} == {"ok"}
