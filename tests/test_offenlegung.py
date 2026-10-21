"""Offenlegungsschreiben für die Verkäuferseite."""

from pathlib import Path

from zitatio.dataroom import DataRoom
from zitatio.offenlegung import to_markdown
from zitatio.pipeline import run_check
from zitatio.report import load_report

GROSS = Path(__file__).resolve().parents[1] / "beispiele" / "gross"


def test_disclosure_letter_lists_facts_per_warranty_and_what_to_fix_first():
    text, data = load_report(GROSS / "dd-bericht.md")
    spa = ("spa-entwurf.md", (GROSS / "spa-entwurf.md").read_text(encoding="utf-8"))
    run = run_check("dd-bericht.md", text, data, DataRoom.from_folder(GROSS / "datenraum"), spa=spa)
    md = to_markdown(run)
    specific, fix = md.split("## 2. Spezifische Offenlegungen")[1].split("## 3. Vor dem Versand bereinigen")
    assert "### Gegen Ziff. 5.6" in specific and "Streitwert CHF 1'450'000" in specific
    assert specific.count("Kontrollwechselklausel DR") == 6
    # Ratschläge an die Käuferin gehören nicht hinein, Widersprüche und SPA-Fehler werden bereinigt
    assert "vor dem Closing einholen" not in specific and "verlangen" not in specific
    assert "Widerspruch im Datenraum: Umsatz 2025" in fix and "Zeichnungsberechtigung: DR 6.1" in fix
    assert "Kaufvertrag: Verkauft werden 12'000 Aktien" in fix and "Datenschutz" in fix
    assert "| DR 2.3 | Jahresrechnung 2025 |" in md
