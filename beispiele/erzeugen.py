"""Erzeugt den fiktiven Beispiel-Datenraum "Alpenblick Präzision AG" als PDFs und Excel.

Alle Firmen, Personen und Zahlen sind erfunden.
Aufruf: python beispiele/erzeugen.py   (braucht fpdf2 und openpyxl)
"""

from pathlib import Path

from fpdf import FPDF

OUT = Path(__file__).parent / "alpenblick" / "datenraum"

DOCS = {
    "1.1 Handelsregisterauszug.pdf": [
        """Handelsregister des Kantons Zürich - Auszug (fiktiv)

Firma: Alpenblick Präzision AG
UID: CHE-411.872.905
Rechtsform: Aktiengesellschaft
Sitz: Winterthur
Eintragung: 14.03.2011

Aktienkapital: CHF 500'000, eingeteilt in 5'000 Namenaktien zu je CHF 100, vollständig liberiert.

Verwaltungsrat:
- Dr. Andrea Keller, Präsidentin, mit Kollektivunterschrift zu zweien
- Marco Bianchi, Mitglied, mit Kollektivunterschrift zu zweien

Revisionsstelle: Treuhand Töss AG, Winterthur"""
    ],
    "2.1 Jahresrechnung 2025.pdf": [
        """Alpenblick Präzision AG - Jahresrechnung 2025 (fiktiv)

Erfolgsrechnung 1.1. bis 31.12.2025
Nettoerlös aus Lieferungen und Leistungen: CHF 18'450'000
Materialaufwand: CHF 7'930'000
Personalaufwand: CHF 6'780'000
EBITDA: CHF 2'310'000
Jahresgewinn: CHF 1'140'000

Bilanz per 31.12.2025
Flüssige Mittel: CHF 1'350'000
Finanzverbindlichkeiten: CHF 5'550'000
Nettoverschuldung: CHF 4'200'000""",
        """Anhang zur Jahresrechnung 2025

Anzahl Vollzeitstellen im Jahresdurchschnitt: über 50, nicht über 250.
Die Gesellschaft hat Verpflichtungen aus langfristigen Mietverträgen von CHF 1'560'000
(Restlaufzeit bis 31.12.2029).
Eventualverbindlichkeiten bestehen keine.""",
    ],
    "3.2.1 Mietvertrag Werk Winterthur.pdf": [
        """Mietvertrag für Geschäftsräume (fiktiv)

Vermieterin: Immobilien Grüze AG, Winterthur
Mieterin: Alpenblick Präzision AG, Winterthur
Mietobjekt: Produktionshalle und Büros, Grüzefeldstrasse 12, 8404 Winterthur, ca. 4'800 m2""",
        """Art. 3 Mietzins
Der Nettomietzins beträgt CHF 312'000 pro Jahr, zahlbar in monatlichen Raten.
Der Mietzins ist an den Landesindex der Konsumentenpreise gebunden.

Art. 4 Dauer
Das Mietverhältnis beginnt am 1. Januar 2020 und ist fest abgeschlossen bis 31.12.2029.""",
        """Art. 5 Kündigung
Nach Ablauf der festen Dauer kann der Vertrag unter Einhaltung einer Kündigungsfrist
von zwölf Monaten auf das Ende eines Kalenderquartals gekündigt werden.

Art. 6 Kontrollwechsel
Wechselt die Mehrheit der Aktien der Mieterin den Eigentümer, kann die Vermieterin
den Vertrag mit einer Frist von sechs Monaten ausserordentlich kündigen.""",
    ],
    "4.1 Rahmenvertrag Helvetia Rail.pdf": [
        """Rahmenliefervertrag (fiktiv)

zwischen Helvetia Rail Komponenten AG (Kundin) und Alpenblick Präzision AG (Lieferantin)
über die Lieferung von Präzisionsdrehteilen für Drehgestelle.

Laufzeit: bis 30.06.2028. Das Mindestabnahmevolumen beträgt CHF 4'000'000 pro Jahr.""",
        """Ziff. 14 Kontrollwechsel
Bei einem Kontrollwechsel bei der Lieferantin ist die Kundin berechtigt, diesen Vertrag
mit einer Frist von drei Monaten zu kündigen. Die Lieferantin informiert die Kundin
unverzüglich über einen geplanten Kontrollwechsel.

Ziff. 15 Anwendbares Recht
Es gilt schweizerisches Recht. Gerichtsstand ist Zürich.""",
    ],
    "5.3 Darlehensvertrag Zürcher Bank.pdf": [
        """Darlehensvertrag (fiktiv)

Darlehensgeberin: Zürcher Gewerbebank AG
Darlehensnehmerin: Alpenblick Präzision AG

Darlehensbetrag: CHF 3'500'000
Zinssatz: 2,4 % p.a., fest
Fälligkeit: 31.03.2030
Covenant: Nettoverschuldung / EBITDA höchstens 2.5"""
    ],
}


class PDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", size=8)
        self.cell(0, 10, f"Seite {self.page_no()}", align="C")


def build(name: str, pages: list[str]) -> None:
    pdf = PDF(format="A4")
    pdf.set_auto_page_break(False)
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, text)
    pdf.output(str(OUT / name))


def build_plan(name: str) -> None:
    """Businessplan wie aus dem Controlling: Einheit im Kopf, Zahlen ohne Währung."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Plan-ER"
    ws.append(["Alpenblick Präzision AG - Businessplan (fiktiv), in TCHF"])
    ws.append(["Position", 2026, 2027, 2028])
    for row in [("Nettoerlös", 19812, 21240, 22950), ("EBITDA", 2604, 2870, 3215),
                ("Investitionen", 1150, 980, 1020)]:
        ws.append(row)
        for cell in ws[ws.max_row][1:]:
            cell.number_format = "#,##0"
    ws.append(["EBITDA-Marge", 0.1314, 0.1351, 0.1401])
    for cell in ws[ws.max_row][1:]:
        cell.number_format = "0.0%"
    staff = wb.create_sheet("Personal")
    staff.append(["Mitarbeitende (FTE)", 2026, 2027, 2028])
    staff.append(["Produktion", 84, 88, 91])
    staff.append(["Verwaltung", 21, 21, 22])
    wb.save(OUT / name)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, pages in DOCS.items():
        build(name, pages)
        print(OUT / name)
    build_plan("2.2 Businessplan 2026-2028.xlsx")
    print(OUT / "2.2 Businessplan 2026-2028.xlsx")
