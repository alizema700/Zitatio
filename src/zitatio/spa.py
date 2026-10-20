"""Garantien im Kaufvertrag (SPA) gegen die Befunde abgleichen.

Im Entwurf des Aktienkaufvertrags garantiert der Verkäufer, dass keine Klagen hängig sind, alle Verträge gültig
unterschrieben sind, die Jahresrechnung stimmt und so weiter. Was die Prüfung im Datenraum gefunden hat, steht oft
im Widerspruch dazu. Der Verkäufer wird es offenlegen, und was offengelegt ist, deckt die Garantie in der Regel
nicht mehr. Für den Käufer heisst das: pro Garantie die Befunde kennen und vor dem Signing entscheiden, ob eine
Freistellung, eine Closing-Bedingung oder ein tieferer Preis nötig ist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Themen; ein Befund und eine Garantie passen zusammen, wenn sie ein Thema teilen
TOPICS = {
    "gesellschaft": r"aktienkapital|aktienbuch|namenaktien|liberiert|capital-actions|capitale azionario",
    "jahresrechnung": r"jahresrechnung|abschl[uü]ss|ertragslage|vermögenslage|comptes annuels|conto annuale",
    "vertraege": r"wesentliche\w* verträge|contrats importants|contratti importanti",
    "kontrollwechsel": r"kontrollwechsel|change of control|changement de contrôle|cambiamento di controllo",
    "finanzierung": r"finanzierung|kredit|leasing|finanzverbindlichkeit|darlehen|crédit|credito",
    "steuern": r"steuer|impôt|imposta",
    "recht": r"rechtsstreit|schiedsverfahren|\bverfahren\b|\bklage|litige|procédure|contenzioso",
    "vorsorge": r"vorsorge|pensionskasse|prévoyance|previdenza",
    "immobilien": r"mietvertr|grundstück|immobilie|\bbail\b|locazione",
    "datenraum": r"datenraum|data room|salle de données",
}
_TOPIC_RX = {k: re.compile(v, re.IGNORECASE) for k, v in TOPICS.items()}
_CLAUSE = re.compile(r"^\s*(?:§\s*|ziff(?:er|\.)\s*)?(\d+(?:\.\d+)+)\.?\s+(.+)$", re.IGNORECASE)
_INDEMNITY = re.compile(r"freistell|stellt\b.{0,80}\bfrei\b|schadlos|indemni|tenir indemne|manleva", re.IGNORECASE)

# Was der Käufer tun kann, je nach Art des Befunds
FREISTELLUNG = "Spezifische Freistellung verlangen"
BEDINGUNG = "Als Closing-Bedingung aufnehmen"
NACHREICHEN = "Vor dem Signing nachreichen lassen"
KLAEREN = "Klären und Garantie präzisieren"
PREIS = "In der Kaufpreisformel als Schuld abziehen"


@dataclass
class Issue:
    topics: set[str]
    title: str
    text: str
    action: str
    href: str


@dataclass
class Warranty:
    number: str
    heading: str
    text: str
    topics: set[str]
    issues: list[Issue] = field(default_factory=list)
    covered_by: dict[int, str] = field(default_factory=dict)  # id(Issue) -> Ziffer der Freistellung


def parse_clauses(text: str) -> list[tuple[str, str]]:
    """Nummerierte Ziffern (5.1, § 5.1, Ziff. 5.1) mit ihrem Text bis zur nächsten Ziffer oder Überschrift."""
    clauses: list[list[str]] = []
    for line in text.splitlines():
        m = _CLAUSE.match(line)
        if m:
            clauses.append([m.group(1), m.group(2).strip()])
        elif line.lstrip().startswith("#"):
            if clauses:
                clauses.append(["", ""])  # Abschnitt endet
        elif clauses and clauses[-1][0] and line.strip():
            clauses[-1][1] += " " + line.strip()
    return [(n, t) for n, t in clauses if n]


def _topics(text: str) -> set[str]:
    return {k for k, rx in _TOPIC_RX.items() if rx.search(text)}


def collect_issues(run) -> list[Issue]:
    issues: list[Issue] = []
    flag_topics = {
        "Zeichnungsberechtigung": {"vertraege"}, "Nachgerechnet": {"jahresrechnung"},
        "Kapitalschutz": {"jahresrechnung", "gesellschaft"}, "Revision": {"jahresrechnung"},
        "Covenant": {"finanzierung"}, "Vorsorge": {"vorsorge"}, "Aktienbuch": {"gesellschaft"},
        "Verweise": {"vertraege", "datenraum"},
    }
    actions = {"Zeichnungsberechtigung": "Genehmigung der Gesellschaft vor dem Closing verlangen",
               "Nachgerechnet": KLAEREN, "Kapitalschutz": KLAEREN, "Revision": KLAEREN, "Covenant": FREISTELLUNG,
               "Vorsorge": FREISTELLUNG, "Aktienbuch": NACHREICHEN, "Verweise": NACHREICHEN}
    for fl in run.flags:
        if fl.area == "Protokolle":
            topics = _topics(fl.title) | ({"recht"} if "Rechtsstreit" in fl.title or "Behörden" in fl.title else set())
            if not topics:
                continue
            issues.append(Issue(topics, fl.title, fl.text, FREISTELLUNG, "#pruefungen"))
            continue
        if fl.level != "warnung" or fl.area not in flag_topics:
            continue
        titles = " ".join(d.title for d in run.room.documents if d.index in fl.docs)
        topics = set(flag_topics[fl.area]) | _topics(fl.title) | (_topics(titles) & {"finanzierung", "immobilien"})
        issues.append(Issue(topics, f"{fl.area}: {fl.title}", fl.text, actions[fl.area], "#pruefungen"))

    for c in run.conflicts:
        topics = {"gesellschaft"} if c.metric == "aktienkapital" else {"jahresrechnung"}
        issues.append(Issue(topics | {"datenraum"}, f"Widerspruch im Datenraum: {c.title}", c.describe(), KLAEREN,
                            "#widersprueche"))

    for i in run.closing or []:
        doc = i.terms.doc
        if i.kind == "kontrollwechsel":
            topics = {"kontrollwechsel", "vertraege"} | (_topics(doc.title) & {"finanzierung", "immobilien"})
            issues.append(Issue(topics, f"Kontrollwechselklausel {doc.label} {doc.title}", i.text, BEDINGUNG, "#closing"))
        elif i.text.startswith("Abgelaufen"):
            issues.append(Issue({"vertraege"} | (_topics(doc.title) & {"immobilien"}),
                                f"Abgelaufener Vertrag {doc.label} {doc.title}", i.text, KLAEREN, "#closing"))

    nd = run.netdebt
    if nd is not None:
        from .netdebt import AEHNLICH, EVENTUAL

        for item in nd.items:
            amount = f"CHF {item.amount:,.0f}".replace(",", "'")
            if item.kind == EVENTUAL:
                issues.append(Issue({"recht"}, f"{item.label}, Streitwert {amount}", item.note, FREISTELLUNG,
                                    "#nettoverschuldung"))
            elif item.kind == AEHNLICH:
                topics = _topics(item.label) | ({"finanzierung"} if "leasing" in item.label.lower() else set())
                issues.append(Issue(topics or {"finanzierung"}, f"{item.label}: {amount}",
                                    "Schuldenähnlicher Posten, nicht in den Finanzschulden der Bilanz.", PREIS,
                                    "#nettoverschuldung"))

    for g in run.gaps:
        if not g.present:
            issues.append(Issue({"datenraum"}, f"Fehlt im Datenraum: {g.name}", "", NACHREICHEN, "#unterlagen"))
    return issues


def check_warranties(spa_text: str, run) -> list[Warranty]:
    clauses = parse_clauses(spa_text)
    issues = collect_issues(run)
    indemnities = [(n, _topics(t)) for n, t in clauses if _INDEMNITY.search(t)]
    warranties = []
    for number, text in clauses:
        if _INDEMNITY.search(text):
            continue
        heading = text.split(".", 1)[0] if len(text.split(".", 1)[0]) <= 40 else ""
        # Die Überschrift sagt, worum es geht; Nebenbemerkungen wie "die im Datenraum enthaltenen Verträge"
        # oder "in der Jahresrechnung ausgewiesen" machen eine Garantie nicht zur Garantie über den Datenraum
        primary = _topics(heading)
        topics = primary | (_topics(text) - {"datenraum", "jahresrechnung", "gesellschaft"}) if primary else _topics(text)
        w = Warranty(number, heading, text, topics)
        for issue in issues:
            if issue.topics & topics:
                w.issues.append(issue)
                if issue.action == FREISTELLUNG:
                    cover = next((n for n, t in indemnities if t & issue.topics), None)
                    if cover:
                        w.covered_by[id(issue)] = cover
        warranties.append(w)
    return warranties


def to_markdown(warranties: list[Warranty]) -> str:
    lines = ["# Garantien im SPA und Befunde", ""]
    for w in warranties:
        if not w.issues:
            continue
        lines.append(f"## Ziff. {w.number} {w.heading}".rstrip())
        lines.append("")
        for i in w.issues:
            action = f"abgedeckt durch Freistellung Ziff. {w.covered_by[id(i)]}" if id(i) in w.covered_by else i.action
            lines.append(f"- {i.title}. {action}.")
        lines.append("")
    return "\n".join(lines)
