"""Das Wichtigste für das Investment Committee: die Befunde, die den Deal betreffen, auf einer Seite.

Der Prüfbericht ist lang; das IC liest eine Seite. Hier werden die Ergebnisse aller Prüfungen nach
Gewicht geordnet: zuerst, was den Preis oder das Closing betrifft, dann, was vor dem Signing zu
klären ist. Jeder Punkt verweist auf seinen Abschnitt im Prüfbericht.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .verify import Status

KRITISCH, KLAEREN, INFO = "kritisch", "klären", "info"


@dataclass
class KeyPoint:
    level: str
    title: str
    text: str
    href: str = ""


def _chf(value: Decimal) -> str:
    if abs(value) >= 10**6:
        return f"CHF {value / 10**6:.1f} Mio."
    return f"CHF {value:,.0f}".replace(",", "'")


def _short(text: str, width: int = 90) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


MAX_FLAGS = 5


def key_points(run) -> list[KeyPoint]:
    points: list[KeyPoint] = []
    wrong = [f for f in run.findings if f.status is Status.ABWEICHUNG]
    if wrong:
        examples = "; ".join(f"Aussage {f.claim.number}: {_short(f.claim.clean_text, 70)}" for f in wrong[:3])
        more = f" und {len(wrong) - 3} weitere" if len(wrong) > 3 else ""
        points.append(KeyPoint(KRITISCH, f"{len(wrong)} Aussage{'n' if len(wrong) != 1 else ''} widersprechen dem Datenraum",
                               f"{examples}{more}.", f"#a{wrong[0].claim.number}"))

    v = run.valuation
    if v is not None and v.impacts and v.equity:
        delta = v.checked_equity - v.equity
        risk = f" Dazu Risiken von {_chf(-sum(i.amount for i in v.risks))} (Klagen)." if v.risks else ""
        points.append(KeyPoint(KRITISCH, f"Preiswirkung der Befunde: {'−' if delta < 0 else '+'}{_chf(abs(delta))} "
                               f"({'−' if delta < 0 else '+'}{abs(delta / v.equity * 100):.1f} %)",
                               f"Equity Value {_chf(v.equity)} laut Rechnung, {_chf(v.checked_equity)} nach Abzug von "
                               + ", ".join(i.label for i in v.impacts) + "." + risk, "#preis"))

    # Warnsignale: die ersten einzeln, der Rest in einem Punkt, damit die Preiswirkung oben sichtbar bleibt
    warnings = [fl for fl in run.flags if fl.level == "warnung"]
    shown = warnings if len(warnings) <= MAX_FLAGS + 1 else warnings[:MAX_FLAGS]
    for fl in shown:
        points.append(KeyPoint(KRITISCH, f"{fl.area}: {fl.title}", _short(fl.text, 220), "#pruefungen"))
    rest = warnings[len(shown):]
    if rest:
        points.append(KeyPoint(KRITISCH, f"{len(rest)} weitere Warnsignale",
                               "; ".join(f"{fl.area}: {_short(fl.title, 80)}" for fl in rest) + ".", "#pruefungen"))

    if run.closing:
        from .terms import revenue_at_risk

        coc = {id(i.terms) for i in run.closing if i.kind == "kontrollwechsel"}
        risk = revenue_at_risk(run.closing)
        if coc:
            share = risk / run.revenue[1] if run.revenue and run.revenue[1] else None
            amount = f", zusammen {_chf(risk)} jährliches Volumen" if risk else ""
            amount += f" ({share * 100:.0f} % des Umsatzes {run.revenue[0]})" if share else ""
            level = KRITISCH if share is not None and share >= Decimal("0.1") else KLAEREN
            points.append(KeyPoint(level, f"{len(coc)} Verträge mit Kontrollwechselklausel",
                                   f"Die Gegenparteien können beim Closing kündigen{amount}. Zustimmungen vor dem "
                                   "Signing einholen.", "#closing"))
        expired = [i for i in run.closing if i.kind == "laufzeit" and i.text.startswith("Abgelaufen")]
        ending = [i for i in run.closing if i.kind == "laufzeit" and not i.text.startswith("Abgelaufen")]
        if expired:
            points.append(KeyPoint(KLAEREN, f"{len(expired)} Vertr{'äge' if len(expired) != 1 else 'ag'} abgelaufen",
                                   ", ".join(f"{i.terms.doc.label} {i.terms.doc.title}" for i in expired) + ".",
                                   "#closing"))
        if ending:
            points.append(KeyPoint(KLAEREN, f"{len(ending)} Verträge enden in den nächsten 18 Monaten",
                                   ", ".join(i.terms.doc.label for i in ending) + ".", "#closing"))

    for c in run.addbacks:
        if c.unsupported:
            amount = sum((v for f, v in c.items if any(f is u for u in c.unsupported)), Decimal(0))
            points.append(KeyPoint(KLAEREN, f"{len(c.unsupported)} EBITDA-Bereinigung{'en' if len(c.unsupported) != 1 else ''} ohne Beleg",
                                   f"{_chf(amount)} im bereinigten EBITDA sind im Datenraum nicht belegt. "
                                   "Bei einem Multiple wirkt das direkt auf den Preis.", "#bereinigungen"))
        if not c.ok:
            points.append(KeyPoint(KRITISCH, "Bereinigtes EBITDA rechnet nicht",
                                   f"Nachgerechnet {_chf(c.expected)}, Bericht {_chf(c.stated)}.", "#bereinigungen"))

    nd = run.netdebt
    if nd is not None:
        from .netdebt import AEHNLICH, EVENTUAL

        similar = [i for i in nd.items if i.kind == AEHNLICH]
        if similar:
            extra = sum((i.amount for i in similar), Decimal(0))
            points.append(KeyPoint(KLAEREN, f"{_chf(extra)} schuldenähnliche Posten",
                                   f"Zusätzlich zur Nettoverschuldung von {_chf(nd.net_debt)}: "
                                   + ", ".join(i.label for i in similar) + ". Im SPA als Schuld verhandeln.",
                                   "#nettoverschuldung"))
        for i in (i for i in nd.items if i.kind == EVENTUAL):
            points.append(KeyPoint(KLAEREN, f"{i.label}: {_chf(i.amount)} Streitwert",
                                   "Nicht bilanziert. Im SPA mit Freistellung oder Rückbehalt absichern.",
                                   "#nettoverschuldung"))
    if run.conflicts:
        names = ", ".join(c.title for c in run.conflicts[:4])
        points.append(KeyPoint(KLAEREN, f"{len(run.conflicts)} Widersprüche im Datenraum",
                               f"Verschiedene Dokumente nennen verschiedene Werte für {names}.", "#widersprueche"))
    if run.internal:
        points.append(KeyPoint(KLAEREN, f"{len(run.internal)} Widersprüche im Bericht",
                               "Der Bericht nennt für " + ", ".join(c.title for c in run.internal[:4])
                               + " an verschiedenen Stellen verschiedene Werte.", "#bericht-widersprueche"))
    places = [f for f in run.findings if f.status in (Status.FALSCHE_FUNDSTELLE, Status.QUELLE_FEHLT)]
    if places:
        points.append(KeyPoint(KLAEREN, f"{len(places)} Fundstelle{'n' if len(places) != 1 else ''} falsch oder fehlend",
                               "Die Werte stimmen zum Teil, aber die Quelle im Bericht führt nicht dorthin.",
                               f"#a{places[0].claim.number}"))
    missing = [g.name for g in run.gaps if not g.present]
    if missing:
        points.append(KeyPoint(INFO, f"{len(missing)} übliche Unterlagen fehlen", ", ".join(missing) + ".", "#unterlagen"))
    touched = [w for w in run.warranties if w.issues]
    if touched:
        names = ", ".join(f"{w.number} {w.heading}".strip() for w in touched[:6])
        open_risks = sum(1 for w in touched for i in w.issues if i.action.startswith("Spezifische") and id(i) not in w.covered_by)
        extra = f" {open_risks} Risiken ohne Freistellung im Entwurf." if open_risks else ""
        points.append(KeyPoint(KLAEREN, f"{len(touched)} von {len(run.warranties)} SPA-Garantien von Befunden berührt",
                               f"Ziff. {names}.{extra}", "#garantien"))

    from .questions import HOCH, request_list

    questions = request_list(run)
    if questions:
        high = sum(1 for q in questions if q.priority == HOCH)
        points.append(KeyPoint(INFO, f"{len(questions)} Fragen an den Verkäufer",
                               f"Davon {high} mit hoher Priorität, bereit für den Q&A-Prozess.", "#fragen"))
    if run.stale:
        docs = sorted({d for ds in run.stale.values() for d in ds})
        first = min(run.stale)
        points.append(KeyPoint(KLAEREN, f"{len(run.stale)} Entscheide neu nötig: Dokumente geändert",
                               f"Seit dem letzten Prüfbericht haben sich {', '.join(docs)} geändert. Die Entscheide zu "
                               "Aussagen, die diese Dokumente zitieren, wurden nicht übernommen.", f"#a{first}"))
    if run.diff is not None:
        o = run.diff.outcomes()
        points.append(KeyPoint(INFO, "Gegenüber der Vorversion",
                               f"{o['behoben']} Befunde behoben, {o['offen']} offen, {o['neuer Befund']} neu.",
                               "#versionen"))
    order = {KRITISCH: 0, KLAEREN: 1, INFO: 2}
    return sorted(points, key=lambda p: order[p.level])


def to_markdown(run) -> str:
    """Eine Seite für das IC-Memo: die wichtigsten Punkte und die offenen Befunde mit Fundstelle."""
    from .render import ORDER

    counts = run.counts()
    lines = [f"# Prüfung {run.report_name}", "",
             f"{len(run.findings)} Aussagen gegen {len(run.room.documents)} Dokumente geprüft, "
             f"{run.created:%d.%m.%Y}. " + ", ".join(f"{n} {s.label}" for s, n in counts.items() if n) + ".", "",
             "## Das Wichtigste", ""]
    marks = {KRITISCH: "**Kritisch:**", KLAEREN: "**Klären:**", INFO: "Hinweis:"}
    for p in key_points(run):
        lines.append(f"- {marks[p.level]} {p.title}. {p.text}")
    open_findings = [f for f in run.findings if f.status not in (Status.GEPRUEFT, Status.UNGEPRUEFT)]
    if open_findings:
        lines += ["", "## Offene Befunde", "", "| Nr | Aussage | Status | Fundstelle | Begründung |", "|---|---|---|---|---|"]
        for f in sorted(open_findings, key=lambda f: (ORDER.index(f.status), f.claim.number)):
            cell = lambda t: t.replace("|", "/").replace("\n", " ")  # noqa: E731
            where = ", ".join(c.label for c in f.claim.citations) or "keine"
            lines.append(f"| {f.claim.number} | {cell(f.claim.clean_text)} | {f.status.label} | {where} | "
                         f"{cell(' '.join(f.reasons))} |")
    return "\n".join(lines) + "\n"
