"""Entwurf eines Offenlegungsschreibens (Disclosure Letter) für die Verkäuferseite.

Was die Verkäuferin vor dem Signing offenlegt, kann die Käuferin später nicht als Garantieverletzung geltend
machen (je nach SPA-Klausel zur Kenntnis der Käuferin). Zitatio ordnet die Befunde aus dem Datenraum den Garantien
des SPA-Entwurfs zu und schreibt je Garantie die spezifischen Offenlegungen mit Fundstelle. Dazu kommen die
allgemeine Offenlegung des Datenraums (jedes Dokument mit SHA-256, damit der Stand später belegbar ist) und eine
Liste, was vor dem Versand zu korrigieren oder nachzureichen ist: Widersprüche und fehlende Unterlagen legt man
nicht offen, man bereinigt sie.

Ein Entwurf für die Anwälte der Verkäuferin, keine Rechtsberatung.
"""

from __future__ import annotations

import re

from .spa import NACHREICHEN, PREIS, TEILLIQUIDATION, Issue, check_warranties, collect_issues
from .swiss import company_name

_TOPIC_NAMES = {"gesellschaft": "Gesellschaft und Aktien", "jahresrechnung": "Jahresrechnung",
                "vertraege": "Wesentliche Verträge", "kontrollwechsel": "Kontrollwechsel",
                "finanzierung": "Finanzierung", "steuern": "Steuern", "recht": "Rechtsstreitigkeiten",
                "vorsorge": "Vorsorge", "immobilien": "Immobilien und Mietverträge", "personal": "Arbeitsverhältnisse",
                "datenraum": "Datenraum", "leakage": "Leakage"}


# Was die Verkäuferin vor dem Versand selbst in Ordnung bringt, statt es offenzulegen
_FIX = {"Nachgerechnet", "Zeichnungsberechtigung", "Datenschutz"}
_SENTENCE_END = re.compile(r"(?<!\bS)(?<!Art)(?<!\bDr)(?<!\bNr)(?<!Ziff)(?<!Abs)\.\s+(?=[A-ZÄÖÜ«])")


def _correct_first(issue: Issue) -> bool:
    return (issue.action == NACHREICHEN or issue.area in _FIX
            or issue.title.startswith(("Widerspruch im Datenraum", "Nachgerechnet")))


def _disclosable(issue: Issue) -> bool:
    if issue.action in (PREIS, TEILLIQUIDATION) or _correct_first(issue):
        return False
    return issue.area not in ("Kaufvertrag", "Leakage", "Sanktionen")


def _entry(issue: Issue) -> str:
    """Titel und der erste Satz des Befunds: die Tatsache mit Fundstelle, ohne Rat an die Käuferin."""
    fact = _SENTENCE_END.split(issue.text.strip(), maxsplit=1)[0].rstrip(".")
    if not fact or fact in issue.title:
        return f"- {issue.title}."
    return f"- {issue.title}. {fact}" + ("" if fact.endswith(("»", "!", "?")) else ".")


def to_markdown(run) -> str:
    company = company_name(run.room)
    out = ["# Offenlegungsschreiben (Entwurf)", "",
           f"Die Verkäuferin legt der Käuferin zum Aktienkaufvertrag über die {company or 'Gesellschaft'} die folgenden "
           "Tatsachen offen. Ein Entwurf aus Zitatio für die Anwälte der Verkäuferin; jede Offenlegung nennt die "
           "Fundstelle im Datenraum.", "", "## 1. Allgemeine Offenlegung", "",
           "Als offengelegt gilt der Inhalt des Datenraums mit den folgenden Dokumenten (SHA-256 der Datei, damit der "
           "Stand belegbar bleibt):", "", "| Dokument | Titel | SHA-256 |", "|---|---|---|"]
    out += [f"| {d.label} | {d.title} | {d.sha256[:16]}… |" for d in run.room.documents if d.index]

    out += ["", "## 2. Spezifische Offenlegungen", ""]
    disclosed = 0
    if getattr(run, "spa_text", None):
        seen: set[str] = set()
        for w in check_warranties(run.spa_text, run):
            items = [i for i in w.issues if _disclosable(i) and i.title not in seen]
            if not items:
                continue
            seen |= {i.title for i in items}
            out += [f"### Gegen Ziff. {w.number} {w.heading}".rstrip(), ""] + [_entry(i) for i in items] + [""]
            disclosed += len(items)
    else:
        by_topic: dict[str, list[Issue]] = {}
        for i in collect_issues(run):
            if _disclosable(i):
                by_topic.setdefault(sorted(i.topics)[0], []).append(i)
        for topic, items in by_topic.items():
            out += [f"### {_TOPIC_NAMES.get(topic, topic.capitalize())}", ""] + [_entry(i) for i in items] + [""]
            disclosed += len(items)
    if not disclosed:
        out += ["Keine spezifischen Offenlegungen aus dem Datenraum.", ""]

    fix = [i for i in collect_issues(run) if _correct_first(i)]
    fix += [Issue(set(), f"{fl.area}: {fl.title}", fl.text, "", "", fl.area) for fl in run.flags
            if fl.level == "warnung" and fl.area in ("Datenschutz", "Kaufvertrag")]
    if fix:
        out += ["## 3. Vor dem Versand bereinigen", "",
                "Diese Punkte gehören nicht ins Schreiben: Widersprüche korrigieren, fehlende Unterlagen und "
                "Genehmigungen nachholen, Personendaten schwärzen, den Vertragsentwurf anpassen.",
                ""] + [f"- {i.title}" for i in dict((i.title, i) for i in fix).values()] + [""]
    return "\n".join(out)
