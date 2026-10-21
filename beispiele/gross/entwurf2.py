"""Zweiten Entwurf des DD-Berichts erzeugen: einige Befunde korrigiert, einer neu dazugekommen.

Für den Versionsvergleich: zitatio pruefen dd-bericht-v2.md -d datenraum --vorher dd-bericht.md
"""

from pathlib import Path

HERE = Path(__file__).parent

EDITS = [
    ("Materialaufwand 2025 belief sich auf CHF 9.82 Mio.", "Materialaufwand 2025 belief sich auf CHF 11.04 Mio."),
    ("Das EBITDA 2025 beträgt CHF 5'309 [", "Das EBITDA 2025 beträgt CHF 5.31 Mio. ["),
    ("Jahresgewinn 2025 beläuft sich auf CHF 3.88 Mio.", "Jahresgewinn 2025 beläuft sich auf CHF 3.06 Mio."),
    ("MWST-Normalsatz von 7.7 %", "MWST-Normalsatz von 8.1 %"),
    ("fest bis 31. Dezember 2032", "fest bis 31. Dezember 2031"),
    ("Kündigungsfrist beträgt 12 Monate [DR 5.2, S. 7]", "Kündigungsfrist beträgt 9 Monate [DR 5.2, S. 7]"),
    ("Helvetic Ortho GmbH wird auf CHF 2.69 Mio.", "Helvetic Ortho GmbH wird auf CHF 2.96 Mio."),
    ("Lakeside Dental SA wird auf CHF 2.14 Mio. geschätzt [DR 5.3, S. 3]",
     "Lakeside Dental SA wird auf CHF 2.14 Mio. geschätzt [DR 5.4, S. 3]"),
    # gestrichen: das erfundene Zitat
    ("Die Rechtsvertreterin schreibt: „Das Prozessrisiko ist vernachlässigbar, eine Zahlung ist ausgeschlossen“ "
     "[DR 10.1, S. 4].\n", ""),
    # neu, und falsch: Personalaufwand mit Tippfehler
    ("Der Personalaufwand stieg auf CHF 11.83 Mio. [DR 2.3, S. 4].\n",
     "Der Personalaufwand stieg auf CHF 11.83 Mio. [DR 2.3, S. 4].\n"
     "Im Vorjahr lag der Personalaufwand 2024 bei CHF 11.81 Mio. [DR 2.3, S. 4].\n"),
]


def main() -> None:
    text = (HERE / "dd-bericht.md").read_text(encoding="utf-8")
    for old, new in EDITS:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    (HERE / "dd-bericht-v2.md").write_text(text.replace("Entwurf", "Entwurf 2", 1), encoding="utf-8")


if __name__ == "__main__":
    main()
