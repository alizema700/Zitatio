"""Lückenliste: Welche üblichen DD-Unterlagen fehlen im Datenraum?

Die Liste ist bewusst kurz und allgemein (Schweizer KMU, Share Deal). Sie sagt nicht, dass
ein Dokument zwingend nötig ist, sondern was Käufer und W&I-Versicherer meist erwarten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dataroom import DataRoom, Document
from .tables import years_in

EXPECTED: list[tuple[str, str, str]] = [
    ("Gesellschaft", "Handelsregisterauszug", r"handelsregister"),
    ("Gesellschaft", "Statuten", r"statuten"),
    ("Gesellschaft", "Aktienbuch", r"aktienbuch|aktionärsverzeichnis|anteilbuch"),
    ("Gesellschaft", "Protokolle Verwaltungsrat und Generalversammlung", r"protokoll"),
    ("Finanzen", "Jahresrechnungen der letzten drei Jahre", r"jahresrechnung|jahresabschluss|abschluss \d{4}"),
    ("Finanzen", "Revisionsbericht", r"revisionsbericht|prüfbericht der revisionsstelle"),
    ("Finanzen", "Zwischenabschluss oder Management Accounts", r"management accounts|management reporting|zwischenabschluss|monatsabschluss"),
    ("Finanzen", "Budget oder Businessplan", r"budget|businessplan|planung|forecast"),
    ("Steuern", "Steuerveranlagungen oder Steuererklärungen", r"veranlagung|steuererklärung"),
    ("Steuern", "MWST-Abrechnungen", r"mwst|mehrwertsteuer"),
    ("Immobilien", "Miet- oder Pachtverträge", r"mietvertr|pachtvertr|grundbuch"),
    ("Verträge", "Wesentliche Kunden- und Lieferantenverträge", r"liefervertr|rahmenvertr|kundenvertr|rahmenliefervertr"),
    ("Finanzierung", "Kredit- und Darlehensverträge", r"kredit|darlehen|leasing"),
    ("Personal", "Arbeitsverträge der Geschäftsleitung", r"arbeitsvertr"),
    ("Personal", "Lohn- oder Personalliste", r"lohnliste|personalliste|mitarbeiterliste|lohnjournal"),
    ("Personal", "Pensionskasse", r"pensionskasse|vorsorge|bvg"),
    ("IP und IT", "Patente, Marken, Lizenzen", r"patent|marke|lizenz"),
    ("Versicherungen", "Versicherungspolicen", r"versicherung|police"),
    ("Recht", "Rechtsstreitigkeiten", r"klage|prozess|rechtsstreit|verfahren|litigation"),
    ("Compliance", "Bewilligungen und Zertifikate", r"bewilligung|zertifi|iso \d|konformit"),
]


@dataclass
class Gap:
    area: str
    name: str
    documents: list[Document] = field(default_factory=list)
    note: str = ""

    @property
    def present(self) -> bool:
        return bool(self.documents)


def check_gaps(room: DataRoom) -> list[Gap]:
    docs = [d for d in room.documents if d.index]
    gaps = []
    for area, name, rx in EXPECTED:
        pattern = re.compile(rx, re.IGNORECASE)
        found = [d for d in docs if pattern.search(d.title)]
        gap = Gap(area, name, found)
        if name.startswith("Jahresrechnungen") and found:
            years = sorted({y for d in found for y in years_in(d.title)})
            if years and len(years) < 3:
                gap.note = f"nur {', '.join(map(str, years))}"
        gaps.append(gap)
    return gaps
