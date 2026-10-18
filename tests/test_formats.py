import csv
import io
import zipfile
from pathlib import Path

from zitatio.benchmark import EXPECTED, run_benchmark
from zitatio.cli import main
from zitatio.dataroom import DataRoom
from zitatio.docx import docx_to_text
from zitatio.pipeline import run_check
from zitatio.render import CSV_COLUMNS, to_csv
from zitatio.verify import Status

EXAMPLE = Path(__file__).resolve().parents[1] / "beispiele" / "alpenblick"
NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def make_docx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {NS}><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def p(text, style=None, numbered=False):
    ppr = ""
    if style or numbered:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:numPr/>" if numbered else "") + "</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


PAGE_BREAK = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def test_docx_headings_lists_tables_and_pages():
    table = ("<w:tbl><w:tr><w:tc>" + p("Nettoerlös") + "</w:tc><w:tc>" + p("CHF 18'450'000") + "</w:tc></w:tr></w:tbl>")
    text = docx_to_text(make_docx(p("Finanzen", "Heading1") + p("Punkt eins", numbered=True) + table + PAGE_BREAK + p("Seite zwei")))
    first, second = text.split("\f")
    assert "# Finanzen" in first and "- Punkt eins" in first
    assert "Nettoerlös; CHF 18'450'000" in first
    assert second.strip() == "Seite zwei"


def test_docx_report_and_dataroom(tmp_path):
    room = DataRoom.from_folder(EXAMPLE / "datenraum")
    room.add("6.1 Arbeitsvertrag CEO.docx", make_docx(p("Lohn") + PAGE_BREAK + p("Der Jahreslohn beträgt CHF 240'000.")))
    report = make_docx(p("Personal", "berschrift1") + p("Der CEO verdient CHF 240'000 pro Jahr [DR 6.1, S. 2]."))
    path = tmp_path / "bericht.docx"
    path.write_bytes(report)
    from zitatio.report import load_report

    text, data = load_report(path)
    run = run_check(path.name, text, data, room)
    assert [f.status for f in run.findings] == [Status.GEPRUEFT]
    assert run.findings[0].claim.section == "Personal"


def test_csv_export_is_excel_friendly():
    room = DataRoom.from_folder(EXAMPLE / "datenraum")
    data = (EXAMPLE / "dd-bericht.md").read_bytes()
    out = to_csv(run_check("dd-bericht.md", data.decode(), data, room))
    assert out.startswith("﻿")
    rows = list(csv.reader(io.StringIO(out.lstrip("﻿")), delimiter=";"))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 15
    assert rows[4][4] == "Abweichung"


def test_benchmark_detects_every_planted_error_kind():
    result = run_benchmark(DataRoom.from_folder(EXAMPLE / "datenraum"))
    kinds = result.by_kind()
    assert set(kinds) == set(EXPECTED)
    assert result.accuracy == 1.0, [c.text for c in result.cases if not c.ok]


def test_cli_writes_all_outputs(tmp_path, capsys):
    out = tmp_path / "pb.html"
    assert main(["pruefen", str(EXAMPLE / "dd-bericht.md"), "-d", str(EXAMPLE / "datenraum"), "-o", str(out),
                 "--json", str(tmp_path / "pb.json"), "--csv", str(tmp_path / "pb.csv")]) == 0
    assert out.exists() and (tmp_path / "pb.json").exists() and (tmp_path / "pb.csv").exists()
    assert main(["benchmark", "-d", str(EXAMPLE / "datenraum")]) == 0
    assert "gesamt" in capsys.readouterr().out
