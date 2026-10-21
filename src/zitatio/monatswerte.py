"""Monatsabschlüsse nachrechnen: Ergibt die Summe der Monate den kumulierten Wert?

Management Accounts haben oft ein Blatt pro Monat und eine Übersicht mit "Umsatz kumuliert". Stimmt die Übersicht
nicht mit der Summe der Monate, ist eine der beiden Angaben falsch; meist die Übersicht, die von Hand gepflegt wird.
"""

from __future__ import annotations

import re
from decimal import Decimal

from .dataroom import DataRoom
from .swiss import WARNUNG, Flag
from .verify import _evidence

_MONTHS = ("jan", "feb", "mär", "mar", "apr", "mai", "may", "jun", "jul", "aug", "sep", "okt", "oct", "nov", "dez", "dec",
           "janv", "févr", "mars", "avr", "juin", "juil", "août", "sept", "déc")
_SHEET = re.compile(r"^Blatt:\s*([A-Za-zäéû]+)\.?\s+(\d{4})\s*$", re.MULTILINE)
_ROW = re.compile(r"^([^;\n]{2,60});\s*(-?[\d'’]+(?:\.\d+)?)\s*$", re.MULTILINE)
_CUMULATIVE = re.compile(r"^(.+?)\s+(?:kumuliert|ytd|total|gesamt|cumulé)$", re.IGNORECASE)


def _num(text: str) -> Decimal:
    return Decimal(re.sub(r"['’]", "", text))


def check_monthly_totals(room: DataRoom) -> list[Flag]:
    flags = []
    for doc in room.documents:
        if doc.index is None:
            continue
        sums: dict[str, Decimal] = {}
        months = 0
        overview = []
        for p, text in enumerate(doc.pages, 1):
            sheet = _SHEET.search(text)
            if sheet and sheet.group(1).lower()[:3] in {m[:3] for m in _MONTHS}:
                months += 1
                for m in _ROW.finditer(text):
                    key = m.group(1).strip().lower()
                    sums[key] = sums.get(key, Decimal(0)) + _num(m.group(2))
                continue
            for m in _ROW.finditer(text):
                c = _CUMULATIVE.match(m.group(1).strip())
                if c:
                    overview.append((c.group(1).strip().lower(), _num(m.group(2)), p, m))
        if months < 12:
            continue
        for key, stated, p, m in overview:
            if key not in sums:
                continue
            total = sums[key]
            tolerance = max(Decimal(months), abs(total) * Decimal("0.001"))  # Rundung der Monatswerte
            if abs(total - stated) > tolerance:
                fmt = lambda x: f"{x:,.0f}".replace(",", "'")  # noqa: E731
                flags.append(Flag(
                    WARNUNG, "Nachgerechnet", f"{doc.label}: {m.group(1).strip()} {fmt(stated)}, Summe der Monate {fmt(total)}",
                    f"Die {months} Monatsblätter in {doc.label} {doc.title} ergeben für {key.capitalize()} {fmt(total)}, "
                    f"die Übersicht (S. {p}) nennt {fmt(stated)}, {fmt(stated - total)} mehr. Eine der beiden Angaben "
                    "ist falsch; meist die von Hand gepflegte Übersicht. Wer mit diesem Wert rechnet (Budget, "
                    "Bewertung), rechnet falsch.",
                    [_evidence(doc, p, m.start(2), m.end(2))], [doc.index]))
    return flags


# --- Management Accounts gegen Jahresrechnung ------------------------------------------

_METRICS = {"umsatz": r"^(?:nettoerl[öo]s|umsatz)", "ebitda": r"^ebitda"}


def _statutory(room: DataRoom, year: int, rx: str):
    from .tables import doc_cells, years_in

    for doc in room.documents:
        if not doc.index or not re.search(r"jahresrechnung|jahresabschluss", doc.title, re.I) or year not in years_in(doc.title):
            continue
        for p in range(1, len(doc.pages) + 1):
            for cell in doc_cells(doc, p):
                if cell.year in (None, year) and re.search(rx, cell.label, re.I):
                    return cell.fact.value[1], doc, p, cell
    return None


def check_management_vs_statutory(room: DataRoom) -> list[Flag]:
    """Summe der Monate (Management) gegen die Jahresrechnung: grosse Abweichung heisst Überleitung verlangen."""
    from .swiss import HINWEIS, OK

    flags = []
    for doc in room.documents:
        if doc.index is None:
            continue
        sheets = [(m.group(2), text) for text in doc.pages for m in [_SHEET.search(text)]
                  if m and m.group(1).lower()[:3] in {x[:3] for x in _MONTHS}]
        years = {y for y, _ in sheets}
        if len(sheets) < 12 or len(years) != 1:
            continue
        year = int(years.pop())
        scale = Decimal(1000) if any(re.search(r"\bTCHF\b|in tausend", t, re.I) for _, t in sheets) else Decimal(1)
        for key, rx in _METRICS.items():
            total = sum((_num(m.group(2)) for _, t in sheets for m in _ROW.finditer(t)
                         if re.search(rx, m.group(1).strip(), re.I)), Decimal(0)) * scale
            found = _statutory(room, year, rx)
            if not total or not found:
                continue
            value, sdoc, sp, cell = found
            share = (total - value) / abs(value) * 100
            fmt = lambda x: f"CHF {x:,.0f}".replace(",", "'")  # noqa: E731
            basis = (f"{key.upper() if key == 'ebitda' else key.capitalize()} {year}: Summe der Monate in {doc.label} "
                     f"{fmt(total)}, Jahresrechnung ({sdoc.label}) {fmt(value)}, {share:+.1f} %.")
            ev = [_evidence(sdoc, sp, cell.fact.start, cell.fact.end)]
            if abs(share) > 5:
                flags.append(Flag(HINWEIS, "Management Accounts",
                                  f"{key.upper() if key == 'ebitda' else key.capitalize()} {year} im Management "
                                  f"Reporting {share:+.0f} % gegenüber der Jahresrechnung",
                                  basis + " Abschlussbuchungen erklären oft einen Teil; die Überleitung vom Management "
                                  "Reporting zur Jahresrechnung verlangen und klären, welcher Wert der Bewertung zugrunde liegt.",
                                  ev, [doc.index]))
            else:
                flags.append(Flag(OK, "Management Accounts", f"{key.upper() if key == 'ebitda' else key.capitalize()} "
                                  f"{year}: Management Reporting passt zur Jahresrechnung", basis, ev))
    return flags
