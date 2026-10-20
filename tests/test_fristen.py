"""Fristenkalender aus Verträgen und Ablaufdaten."""

import datetime as dt
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.fristen import deadlines, to_ics
from zitatio.pipeline import run_check
from zitatio.render import to_html, to_json
from zitatio.report import load_report

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def test_deadlines_of_large_case():
    text, data = load_report(GROSS / "dd-bericht.md")
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"))
    items = deadlines(run, today=dt.date(2026, 10, 20))
    by_title = {d.title: d for d in items}
    # 6 Monate Frist auf das Vertragsende 30.06.2028
    lager = by_title["Letzter Kündigungstag: Mietvertrag Lager Heerbrugg"]
    assert lager.date == dt.date(2027, 12, 31) and lager.reference == "DR 4.1.2, S. 4"
    # Kündigung "auf Jahresende" passt nicht zu einem Vertragsende am 30.09.: kein erfundener Termin
    assert "Letzter Kündigungstag: Liefervertrag Helvetic Ortho GmbH" not in by_title
    assert by_title["Vertragsende: Liefervertrag Helvetic Ortho GmbH"].date == dt.date(2027, 9, 30)
    # Ablaufdatum aus der Q&A-Liste; abgelaufene Verträge stehen in der Closing-Liste, nicht im Kalender
    assert any(d.date == dt.date(2027, 11, 14) and d.reference.startswith("DR 12.1") for d in items)
    assert all(d.date >= dt.date(2026, 10, 20) for d in items)
    assert [d.date for d in items] == sorted(d.date for d in items)

    ics = to_ics(items, "Test", stamp=dt.datetime(2026, 10, 20, 12, 0, tzinfo=dt.timezone.utc))
    lines = ics.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and ics.count("BEGIN:VEVENT") == len(items)
    assert all(len(line.encode()) <= 75 for line in lines)
    assert "DTSTART;VALUE=DATE:20271231" in ics and "TRIGGER:-P14D" in ics

    assert 'id="fristen"' in to_html(run) and '"fristen"' in to_json(run)
