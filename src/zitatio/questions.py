"""Fragenliste an den Verkäufer: aus den Befunden eine Liste, die man in den Q&A-Prozess geben kann.

Jeder Befund, den nur der Verkäufer klären kann, wird zu einer Frage mit Fundstelle: fehlende
Unterlagen und Nachträge, Widersprüche zwischen Dokumenten, Warnsignale aus Protokollen und
Handelsregister, Kontrollwechselklauseln, Bereinigungen ohne Beleg und offene Verfahren. Fragen an das
eigene Team (falsche Fundstellen im Bericht) gehören nicht hierher.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .verify import Status

HOCH, MITTEL = "hoch", "mittel"


@dataclass
class Question:
    number: int
    area: str
    priority: str
    text: str
    reference: str  # Fundstelle oder Grund, für den Verkäufer lesbar
    related: str = ""  # Eintrag der Q&A-Liste, der dazu schon etwas sagt ("Q&A 5")


def _chf(value: Decimal) -> str:
    return f"CHF {value:,.0f}".replace(",", "'")


def _where(evidence) -> str:
    return "; ".join(dict.fromkeys(f"{e.doc_label}, S. {e.page}" for e in evidence))


# Formulierung je Prüfbereich; {title} ist der Titel des Warnsignals
_FLAG_QUESTIONS = {
    "Zeichnungsberechtigung": "Bitte Nachweis vorlegen, dass die Unterschrift gültig ist (Vollmacht, Genehmigung "
                              "oder zweite Unterschrift): {title}.",
    "Kapitalschutz": "Bitte Massnahmen nach Art. 725a/725b OR und den aktuellen Stand erläutern: {title}.",
    "Protokolle": "Bitte Stand, finanzielle Auswirkung und allfällige Rückstellung erläutern: {title}.",
    "Verweise": "Bitte nachreichen: {title}.",
    "Covenant": "Bitte Waiver der Bank oder Stellungnahme zur Kreditkündigung vorlegen: {title}.",
    "Vorsorge": "Bitte aktuellen Deckungsgrad und allfällige Sanierungsmassnahmen der Vorsorgeeinrichtung "
                "vorlegen: {title}.",
    "Leakage": "Bitte alle Zahlungen an die Verkäuferin und Nahestehende seit dem Locked-Box-Stichtag auflisten "
               "und belegen: {title}.",
    "Nachgerechnet": "Bitte Abweichung erklären und korrigierte Zahlen vorlegen: {title}.",
    "Revision": "Bitte erläutern: {title}.",
    "MWST": "Bitte MWST-Umsatzabstimmung zur Jahresrechnung vorlegen und Differenzen erklären: {title}.",
    "Datenschutz": "Bitte Personendaten schwärzen und das Dokument neu in den Datenraum stellen: {title}.",
    "Arbeitsrecht": "Bitte betroffene Mitarbeitende und den geschätzten Betrag nennen: {title}.",
    "Aktienbuch": "Bitte vollständiges, nachgeführtes Aktienbuch vorlegen: {title}.",
}


def request_list(run) -> list[Question]:
    items: list[tuple[str, str, str, str]] = []  # Bereich, Priorität, Frage, Fundstelle

    for fl in run.flags:
        if fl.level != "warnung" or fl.area == "Sanktionen":  # Compliance klärt das Team selbst, nicht mit dem Verkäufer
            continue
        template = _FLAG_QUESTIONS.get(fl.area, "Bitte erläutern: {title}.")
        area = "Finanzen" if fl.area == "Nachgerechnet" else fl.area
        items.append((area, HOCH, template.format(title=fl.title), _where(fl.evidence)))

    for c in run.conflicts:
        items.append(("Widersprüche", HOCH, f"Welcher Wert gilt für {c.title}? Die Unterlagen nennen verschiedene "
                      "Werte; bitte den richtigen bestätigen und die Abweichung erklären.",
                      c.describe().split(": ", 1)[-1]))

    seen_coc = set()
    for i in run.closing or []:
        doc = i.terms.doc
        if i.kind == "kontrollwechsel" and doc.label not in seen_coc:
            seen_coc.add(doc.label)
            items.append(("Verträge", HOCH, f"Bitte Zustimmung oder Verzicht der Gegenpartei zum Kontrollwechsel "
                          f"einholen oder Stand mitteilen ({doc.title}).", _where(i.evidence)))
        elif i.kind == "laufzeit":
            end = f"{i.terms.end:%d.%m.%Y}"
            what = (f"Der Vertrag ist am {end} abgelaufen. Wurde er verlängert?" if i.text.startswith("Abgelaufen")
                    else f"Der Vertrag endet am {end}. Ist eine Verlängerung vereinbart?")
            items.append(("Verträge", MITTEL, f"{doc.title}: {what}", _where(i.evidence)))

    for c in run.addbacks:
        for f, value in c.items:
            if any(f is u for u in c.unsupported):
                items.append(("Finanzen", HOCH, f"Bitte Beleg für die EBITDA-Bereinigung von {_chf(abs(value))} "
                              f"vorlegen: «{f.claim.clean_text}»", f"Bericht, Aussage {f.claim.number}"))

    nd = run.netdebt
    if nd is not None:
        from .netdebt import EVENTUAL

        for i in nd.items:
            if i.kind == EVENTUAL:
                items.append(("Recht", HOCH, f"Bitte Stand des Verfahrens, Einschätzung des Prozessrisikos und "
                              f"allfällige Rückstellung mitteilen ({i.label}, Streitwert {_chf(i.amount)}).",
                              _where(i.evidence)))

    for g in run.gaps:
        if not g.present:
            items.append((g.area, MITTEL, f"Bitte {g.name} in den Datenraum stellen.", "fehlt im Datenraum"))
        elif g.note:
            items.append((g.area, MITTEL, f"Bitte die fehlenden {g.name} nachreichen ({g.note} vorhanden).",
                          ", ".join(d.label for d in g.documents)))

    # Aussagen ohne jede Quelle im Datenraum: der Verkäufer soll die Grundlage liefern
    for f in run.findings:
        if f.status is Status.QUELLE_FEHLT and f.claim.citations:
            items.append(("Unterlagen", MITTEL, f"Bitte Dokument zu {', '.join(c.label for c in f.claim.citations)} "
                          "nachreichen; es ist im Bericht zitiert, aber nicht im Datenraum.",
                          f"Bericht, Aussage {f.claim.number}"))

    order = {HOCH: 0, MITTEL: 1}
    items.sort(key=lambda x: order[x[1]])
    questions = [Question(n, area, prio, text, ref) for n, (area, prio, text, ref) in enumerate(items, 1)]
    _link_qa(questions, run.room)
    return questions


def _link_qa(questions: list[Question], room) -> None:
    """Steht in der Q&A-Liste schon ein Eintrag zum Thema, wird er genannt: vielleicht ist die Frage beantwortet."""
    from .locate import _terms

    entries = {n: set(_terms(d.pages[0])) for n, d in room.qa_entries().items() if d.pages}
    for q in questions:
        wanted = set(_terms(q.text))
        best = max(((len(wanted & terms), n) for n, terms in entries.items()), default=(0, 0))
        if best[0] >= 3:
            q.related = f"Q&A {best[1]}"


def to_markdown(questions: list[Question], title: str = "Fragenliste an den Verkäufer") -> str:
    lines = [f"# {title}", "", "| Nr | Bereich | Priorität | Frage | Bezug | Q&A |", "|---|---|---|---|---|---|"]
    cell = lambda t: t.replace("|", "/").replace("\n", " ")  # noqa: E731
    for q in questions:
        lines.append(f"| {q.number} | {q.area} | {q.priority} | {cell(q.text)} | {cell(q.reference)} | {q.related} |")
    return "\n".join(lines) + "\n"
