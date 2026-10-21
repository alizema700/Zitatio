"""Das Wichtigste für das Investment Committee, im Prüfbericht und als Markdown fürs Memo."""

from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_html
from zitatio.report import load_report
from zitatio.summary import key_points, to_markdown

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def test_key_points_of_large_case():
    text, data = load_report(GROSS / "dd-bericht.md")
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"))
    points = key_points(run)
    levels = [p.level for p in points]
    assert levels == sorted(levels, key=["kritisch", "klären", "info"].index)
    titles = " | ".join(p.title for p in points)
    for expected in ("Aussagen widersprechen dem Datenraum", "Zeichnungsberechtigung", "Kontrollwechselklausel",
                     "EBITDA-Bereinigung ohne Beleg", "Widersprüche im Datenraum", "Widerspruch im Bericht"):
        assert expected in titles, expected
    assert all(p.href.startswith("#") for p in points)
    page = to_html(run)
    assert "Das Wichtigste für das Investment Committee" in page
    for p in points:
        if not p.href.startswith("#a"):
            assert f'id="{p.href[1:]}"' in page, p.href
    memo = to_markdown(run)
    assert memo.startswith("# Prüfung dd-bericht.md") and "## Offene Befunde" in memo
