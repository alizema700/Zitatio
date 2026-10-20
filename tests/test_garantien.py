"""Garantien im Kaufvertrag gegen die Befunde abgleichen."""

from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import to_html, to_json
from zitatio.report import load_report
from zitatio.spa import BEDINGUNG, FREISTELLUNG, parse_clauses

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def test_parse_clauses():
    text = "## 5. Garantien\n\n5.1 Gesellschaft. Das Aktienkapital\nist voll liberiert.\n\n§ 5.2 Steuern. Keine.\n\n## 6. Anderes\n\nText."
    assert parse_clauses(text) == [("5.1", "Gesellschaft. Das Aktienkapital ist voll liberiert."),
                                   ("5.2", "Steuern. Keine.")]


def test_warranties_of_large_case():
    text, data = load_report(GROSS / "dd-bericht.md")
    spa = (GROSS / "spa-entwurf.md").read_text(encoding="utf-8")
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"), spa=("spa-entwurf.md", spa))
    by_number = {w.number: w for w in run.warranties}
    assert "6.1" not in by_number  # Freistellung, keine Garantie

    def titles(n):
        return " | ".join(i.title for i in by_number[n].issues)

    assert "Aktienkapital" in titles("5.1")
    assert "rechnet nicht" in titles("5.2") and "Umsatz 2025" in titles("5.2")
    assert "Kontrollwechselklausel DR 5.1" in titles("5.3") and "Zeichnungsberechtigung" in titles("5.3")
    assert "Leasing" in titles("5.4") and "Umsatz" not in titles("5.4")
    assert "Klage DR 10.1" in titles("5.6") and "Vorsorge" in titles("5.7") and "Nachtrag" in titles("5.8")
    assert not by_number["5.9"].issues
    tax = by_number["5.5"]
    assert [tax.covered_by.get(id(i)) for i in tax.issues] == ["6.1"]
    lawsuit = next(i for i in by_number["5.6"].issues if i.title.startswith("Klage"))
    assert lawsuit.action == FREISTELLUNG and id(lawsuit) not in by_number["5.6"].covered_by
    assert all(i.action == BEDINGUNG for i in by_number["5.3"].issues if i.title.startswith("Kontrollwechsel"))
    page = to_html(run)
    assert 'id="garantien"' in page and "abgedeckt durch Freistellung Ziff. 6.1" in page
    assert '"garantien"' in to_json(run)
