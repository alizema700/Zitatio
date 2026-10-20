"""Rechnet der Bericht in sich, rechnet die Erfolgsrechnung?

- Widersprüche im Bericht: Nennt der Bericht für dieselbe Grösse und Periode an zwei Stellen
  verschiedene Werte (gerundete Schreibweisen zählen als gleich)?
- Erfolgsrechnung nachgerechnet: In jeder Spalte einer Erfolgsrechnung im Datenraum muss
  EBITDA = Umsatz − Material − Personal − übriger Aufwand, EBIT = EBITDA − Abschreibungen und
  Gewinn = EBIT − Finanzaufwand − Steuern aufgehen. Sonst ist eine Zeile falsch übertragen.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .dataroom import DataRoom
from .facts import AMOUNT, MONTHS, format_value
from .swiss import WARNUNG, Flag
from .tables import LABELS, doc_cells, is_plan
from .verify import Finding, Status, _context, _evidence


@dataclass
class ReportConflict:
    title: str
    findings: list[Finding]
    values: list[str]


_GERMAN_MONTHS = ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
                  "november", "dezember"]


def report_conflicts(findings: list[Finding]) -> list[ReportConflict]:
    groups: dict[tuple[str, str], list[tuple[Finding, object]]] = defaultdict(list)
    for f in findings:
        amounts = [x for x in f.claim.facts if x.kind == AMOUNT]
        if len(amounts) != 1 or is_plan(f.claim.clean_text):
            continue
        ctx = _context(f.claim, amounts[0])
        text = f.claim.clean_text.lower()
        if re.search(r"unternehmenswert|equity value|enterprise value|kaufpreis|-fache|quartal|\bq[1-4]\b|halbjahr|\bh[12]\b|monat|trimestre|semestre|\bmois\b|\bmese\b", text):
            continue
        month = next((m for m in MONTHS if re.search(rf"\b{m}\b", text)), "")
        month = _GERMAN_MONTHS[MONTHS[month] - 1] if month else ""
        if ctx.metric and ctx.year and len(ctx.metrics) == 1:
            groups[(ctx.metric, f"{month.capitalize()} {ctx.year}".strip())].append((f, amounts[0]))
    out = []
    for (metric, year), items in groups.items():
        distinct: list[tuple[Finding, object]] = []
        for f, fact in items:
            if not any(fact.match(g) or g.match(fact) for _, g in distinct):
                distinct.append((f, fact))
        if len(distinct) < 2:
            continue
        label = LABELS[metric]
        title = f"{label[0].upper()}{label[1:]} {year}"
        conflict = ReportConflict(title, [f for f, _ in items], [x.display() for _, x in distinct])
        out.append(conflict)
        for f, fact in items:
            others = [f"{g.display()} (Aussage {o.claim.number})" for o, g in items
                      if o is not f and not (fact.match(g) or g.match(fact))]
            if not others:
                continue
            f.reasons.append(f"Der Bericht nennt für {title} an anderer Stelle {', '.join(others)}.")
            if f.status in (Status.UNGEPRUEFT, Status.OHNE_BELEG):
                f.status = Status.WIDERSPRUCH
    return out


# --- Erfolgsrechnung nachrechnen ------------------------------------------------------

_LINES = {
    "umsatz": r"nettoerl[öo]s|^umsatz|betriebsertrag|chiffre d'affaires|produits nets|ricavi netti|cifra d'affari",
    "material": r"materialaufwand|warenaufwand|charges de matériel|charges de marchandises|costi (?:del|per il) materiale",
    "personal": r"personalaufwand|charges de personnel|costi (?:del|per il) personale",
    "uebriger": r"übriger betrieblicher aufwand|sonstiger betrieblicher aufwand|übriger aufwand"
                r"|autres charges d'exploitation|altri costi d'esercizio",
    "ebitda": r"^ebitda\b",
    "abschreibungen": r"^abschreibungen|^amortissements|^ammortamenti",
    "ebit": r"^betriebsergebnis|^ebit\b|^résultat d'exploitation|^risultato operativo",
    "finanzaufwand": r"^finanzaufwand|^charges financières|^oneri finanziari",
    "steuern": r"^steuern|^ertragssteuern|^direkte steuern|^impôts|^imposte",
    "gewinn": r"^jahresgewinn|^jahresergebnis|^reingewinn|^bénéfice|^résultat de l'exercice|^utile",
}
# Ohne eines dieser Wörter hat eine Seite keine Zwischensumme, die sich nachrechnen liesse
_TOTALS = ("ebitda", "ebit", "betriebsergebnis", "jahresgewinn", "jahresergebnis", "reingewinn", "résultat",
           "bénéfice", "utile", "risultato")
_RULES = [
    ("EBITDA", "ebitda", ["umsatz"], ["material", "personal", "uebriger"]),
    ("EBIT", "ebit", ["ebitda"], ["abschreibungen"]),
    ("Jahresgewinn", "gewinn", ["ebit"], ["finanzaufwand", "steuern"]),
]


def check_income_statements(room: DataRoom) -> list[Flag]:
    flags = []
    for doc in room.documents:
        if doc.index is None:
            continue
        for p in range(1, len(doc.pages) + 1):
            lower = doc.pages[p - 1].lower()
            if not any(w in lower for w in _TOTALS):
                continue
            columns: dict[int | None, dict[str, object]] = defaultdict(dict)
            for cell in doc_cells(doc, p):
                label = cell.label.lower()
                for key, rx in _LINES.items():
                    if re.search(rx, label) and key not in columns[cell.year]:
                        columns[cell.year][key] = cell
                        break
            for year, cells in columns.items():
                for name, total, plus, minus in _RULES:
                    needed = [total] + plus + minus
                    if not all(k in cells for k in needed):
                        continue
                    value = lambda k: cells[k].fact.value[1]  # noqa: E731
                    expected = sum((value(k) for k in plus), Decimal(0)) - sum((value(k) for k in minus), Decimal(0))
                    stated = value(total)
                    tolerance = max(cells[k].fact.precision or Decimal(1) for k in needed) * len(needed)
                    if abs(expected - stated) <= tolerance:
                        continue
                    when = f" {year}" if year else ""
                    chf = lambda x: format_value(AMOUNT, ("CHF", x))  # noqa: E731
                    flags.append(Flag(
                        WARNUNG, "Nachgerechnet", f"{doc.label}, S. {p}: {name}{when} rechnet nicht",
                        f"Aus den Zeilen ergibt sich {chf(expected)}, ausgewiesen sind {chf(stated)} "
                        f"(Differenz {chf(stated - expected)}). Eine Zeile ist falsch übertragen oder verändert.",
                        [_evidence(doc, p, cells[k].fact.start, cells[k].fact.end) for k in [total] + minus[:1]],
                        [doc.index]))
    return flags
