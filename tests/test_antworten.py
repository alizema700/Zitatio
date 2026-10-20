"""Antwortentwürfe für Käuferfragen aus dem Datenraum."""

from pathlib import Path

from zitatio.antworten import answer, read_questions, to_markdown
from zitatio.dataroom import DataRoom

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"
QUESTIONS = {
    "Wie hoch ist das Aktienkapital?": ("DR 1.1, S. 1", "1'200'000"),
    "Wann endet der Mietvertrag für das Büro in Zürich?": ("DR 4.1.3, S. 2", "31.03.2027"),
    "Hat der Kreditvertrag eine Kontrollwechselklausel?": ("DR 6.1, S. 5", "Kontrollwechsel"),
    "Wie hoch ist der Deckungsgrad der Pensionskasse?": ("DR 7.3, S. 2", "112.4 %"),
    "Wie hoch war der Umsatz 2024?": ("DR 2.2, S. 3", "29'540'118"),
    "Wann läuft das ISO-Zertifikat ab?": ("DR 12.1, S. 1", "14.11.2027"),
    "Wie hoch ist der Streitwert der Klage von Nordlicht?": ("DR 10.1, S. 2", "1'450'000"),
    "Wie lange ist die Kündigungsfrist im Liefervertrag mit Alpstein Kliniken?": ("DR 5.1, S. 7", "3 Monaten"),
}


def test_answers_cite_the_right_page():
    room = DataRoom.from_folder(GROSS / "datenraum")
    answers = answer(list(QUESTIONS) + ["Besitzt die Gesellschaft Kryptowährungen?"], room)
    for a in answers[:-1]:
        where, value = QUESTIONS[a.question]
        assert (a.reference, value in a.text) == (where, True), a
    # Nichts erfinden
    assert answers[-1].text == "" and "nicht gefunden" in to_markdown(answers)
    # Der Datenraum nennt zwei Werte für das Aktienkapital: die Antwort sagt es
    assert "CHF 1'000'000" in answers[0].warning


def test_questions_from_text_and_excel():
    text = "# Fragen\n1. Wie hoch ist der Umsatz?\n- Gibt es Rechtsstreitigkeiten?\n\n| 3 | Wer prüft die Bücher? |\n"
    assert read_questions(text.encode(), ".md") == ["Wie hoch ist der Umsatz?", "Gibt es Rechtsstreitigkeiten?",
                                                    "Wer prüft die Bücher?"]
    xlsx = (GROSS / "datenraum" / "12.1 Q&A-Liste Projekt Säntis.xlsx").read_bytes()
    questions = read_questions(xlsx, ".xlsx")
    assert len(questions) == 5 and questions[0].startswith("Wie hoch ist der Auftragsbestand")
