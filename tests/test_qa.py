"""Q&A-Liste des Datenraums als Quelle: "[Q&A 17]" zitiert genau einen Eintrag."""

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_html
from zitatio.report import parse_citations
from zitatio.verify import Status

QA = ("Q&A-Liste Projekt Alpstein\nNr; Frage; Antwort; Datum\n"
      "17; Wie hoch ist der Auftragsbestand per 30.06.2026?; Der Auftragsbestand beträgt CHF 4'200'000.; 12.07.2026\n"
      "18; Gibt es laufende Steuerprüfungen?; Nein, die letzte Prüfung endete am 31.03.2024 ohne Nachforderung.; 12.07.2026\n"
      "19; Wie viele Mitarbeitende hat die Gesellschaft?; Per 30.06.2026 sind es 142 Mitarbeitende\n"
      "auf 131 Vollzeitstellen.; 14.07.2026\n")


def _room() -> DataRoom:
    room = DataRoom()
    room.add("12.1 Q&A-Liste.txt", QA.encode())
    return room


def test_qa_citation_is_parsed():
    c, d = parse_citations("Text [Q&A Nr. 17; DR 2.3, S. 4].")
    assert c.label == "Q&A 17" and d.label == "DR 2.3, S. 4"


def test_qa_entries_are_their_own_sources():
    room = _room()
    assert sorted(room.qa_entries()) == [17, 18, 19]
    assert "131 Vollzeitstellen" in room.get("Q&A 19").pages[0]
    report = ("Der Auftragsbestand per 30.06.2026 beträgt CHF 4.2 Mio. [Q&A 17].\n\n"
              "Die letzte Steuerprüfung endete am 31.03.2024 ohne Nachforderung [Q&A 18].\n\n"
              "Der Auftragsbestand per 30.06.2026 beträgt CHF 4.2 Mio. [Q&A 19].\n\n"
              "Die Gesellschaft beschäftigt 131 Vollzeitstellen [Q&A 20].")
    run = run_check("b.md", report, report.encode(), room)
    statuses = [f.status for f in run.findings]
    assert statuses[:2] == [Status.GEPRUEFT, Status.GEPRUEFT]
    assert statuses[2] is not Status.GEPRUEFT  # steht in Eintrag 17, nicht 19
    assert statuses[3] is Status.QUELLE_FEHLT
    assert "Q&amp;A 17" in to_html(run) or "Q&A 17" in to_html(run)
