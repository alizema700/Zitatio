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
