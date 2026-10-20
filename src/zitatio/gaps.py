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
    ("Gesellschaft", "Handelsregisterauszug", r"handelsregister|registre du commerce|registro di commercio"),
    ("Gesellschaft", "Statuten", r"statuten|statuts|statuto"),
    ("Gesellschaft", "Aktienbuch", r"aktienbuch|aktionärsverzeichnis|anteilbuch|registre des actions|libro delle azioni"),
    ("Gesellschaft", "Protokolle Verwaltungsrat und Generalversammlung", r"protokoll|procès-verba|verbal"),
    ("Finanzen", "Jahresrechnungen der letzten drei Jahre", r"jahresrechnung|jahresabschluss|abschluss \d{4}|comptes annuels|conto annuale"),
    ("Finanzen", "Revisionsbericht", r"revisionsbericht|prüfbericht der revisionsstelle|rapport de l'organe de révision|rapporto dell'ufficio di revisione"),
    ("Finanzen", "Zwischenabschluss oder Management Accounts", r"management accounts|management reporting|zwischenabschluss|monatsabschluss"),
    ("Finanzen", "Budget oder Businessplan", r"budget|businessplan|planung|forecast|preventivo"),
    ("Steuern", "Steuerveranlagungen oder Steuererklärungen", r"veranlagung|steuererklärung|taxation|déclaration d'impôt|tassazione|dichiarazione d'imposta"),
    ("Steuern", "MWST-Abrechnungen", r"mwst|mehrwertsteuer|\btva\b|\biva\b"),
    ("Immobilien", "Miet- oder Pachtverträge", r"mietvertr|pachtvertr|grundbuch|bail|contratto di locazione|registre foncier"),
    ("Verträge", "Wesentliche Kunden- und Lieferantenverträge", r"liefervertr|rahmenvertr|kundenvertr|rahmenliefervertr|contrat de livraison|contrat-cadre|contratto di fornitura|contratto quadro"),
    ("Finanzierung", "Kredit- und Darlehensverträge", r"kredit|darlehen|leasing|crédit|prêt|credito|mutuo"),
    ("Personal", "Arbeitsverträge der Geschäftsleitung", r"arbeitsvertr|contrat de travail|contratto di lavoro"),
    ("Personal", "Lohn- oder Personalliste", r"lohnliste|personalliste|mitarbeiterliste|lohnjournal|liste du personnel|liste des salaires|elenco del personale"),
    ("Personal", "Pensionskasse", r"pensionskasse|vorsorge|bvg|caisse de pension|prévoyance|lpp|cassa pensione|previdenza"),
    ("IP und IT", "Patente, Marken, Lizenzen", r"patent|marke|lizenz|brevet|marque|licence|brevetto|marchio|licenza"),
    ("Versicherungen", "Versicherungspolicen", r"versicherung|police|assurance|assicurazion|polizza"),
    ("Recht", "Rechtsstreitigkeiten", r"klage|prozess|rechtsstreit|verfahren|litigation|litige|procédure|causa|contenzioso"),
    ("Compliance", "Bewilligungen und Zertifikate", r"bewilligung|zertifi|iso \d|konformit|autorisation|certifica|autorizzazion"),
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
