"""Fragenliste an den Verkäufer aus den Befunden."""

import io
import zipfile
from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.excel import to_xlsx
from zitatio.pipeline import run_check
from zitatio.questions import request_list, to_markdown
from zitatio.render import to_html, to_json
from zitatio.report import load_report

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def test_questions_of_large_case():
    text, data = load_report(GROSS / "dd-bericht.md")
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"))
    questions = request_list(run)
    texts = " | ".join(q.text for q in questions)
    for expected in ("Nachtrag Nr. 1", "Steuerprüfung", "Welcher Wert gilt für Umsatz 2025",
                     "Kontrollwechsel", "EBITDA-Bereinigung von CHF 120'000", "Prozessrisikos",
                     "Lohn- oder Personalliste"):
        assert expected in texts, expected
    priorities = [q.priority for q in questions]
    assert priorities == sorted(priorities, key=["hoch", "mittel"].index)
    assert [q.number for q in questions] == list(range(1, len(questions) + 1))
    # Datumsangaben bleiben ganz
    assert any("31.03.2027" in q.text for q in questions)
    # Falsche Fundstellen im Bericht sind Sache des eigenen Teams, keine Frage an den Verkäufer
    assert "Fundstelle" not in texts

    md = to_markdown(questions)
    assert md.count("\n| ") == len(questions) + 1
    page = to_html(run)
    assert 'id="fragen"' in page
    assert '"fragenliste"' in to_json(run)
    with zipfile.ZipFile(io.BytesIO(to_xlsx(run))) as z:
        assert "Fragenliste" in z.read("xl/workbook.xml").decode()


def test_red_flag_report_without_dd_report(tmp_path):
    from zitatio.cli import main

    out = tmp_path / "rf.html"
    questions = tmp_path / "fragen.md"
    assert main(["redflags", "-d", str(GROSS / "datenraum"), "-o", str(out), "--fragen", str(questions),
                 "--spa", str(GROSS / "spa-entwurf.md")]) == 0
    page = out.read_text(encoding="utf-8")
    assert "Red-Flag-Bericht" in page and "Warnsignale im Datenraum" in page
    assert "im Bericht nicht erwähnt" not in page
    assert 'id="garantien"' in page and "Leakage" in page
    assert questions.read_text(encoding="utf-8").startswith("# Fragenliste")


def test_question_names_matching_qa_entry():
    text, data = load_report(GROSS / "dd-bericht.md")
    spa = ("spa-entwurf.md", (GROSS / "spa-entwurf.md").read_text(encoding="utf-8"))
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"), spa=spa)
    questions = request_list(run)
    leakage = next(q for q in questions if "Locked-Box-Stichtag" in q.text)
    assert leakage.related == "Q&A 5"
    # Fragen ohne passenden Eintrag bleiben ohne Verweis
    assert sum(1 for q in questions if q.related) == 1
    assert "| Q&A 5 |" in to_markdown(questions)
