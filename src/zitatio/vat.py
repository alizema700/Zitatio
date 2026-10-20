"""MWST-Umsatzabstimmung: deklarierter Umsatz gegen die Jahresrechnung.

Eine Standardprüfung der Steuer-DD in der Schweiz. Die Summe der Ziffer 200 (Total der vereinbarten Entgelte)
aller Quartalsabrechnungen eines Jahres muss zu den Nettoerlösen der Jahresrechnung passen. Eine Lücke heisst
oft: Umsätze nicht deklariert. Die ESTV kann fünf Jahre zurück nachfordern (Art. 42 MWSTG), mit Verzugszins
(Art. 87 MWSTG). Zusätzlich rechnet Zitatio pro Quartal die Steuer auf dem Normalsatz nach.
"""

from __future__ import annotations

import re
from decimal import Decimal

from .dataroom import DataRoom, Document
from .facts import format_value
from .swiss import HINWEIS, OK, WARNUNG, Flag, _latest_statement
from .tables import years_in
from .verify import _evidence

_DOC = re.compile(r"mwst|mehrwertsteuer|\btva\b|\biva\b", re.IGNORECASE)
_NUM = r"CHF\s*([\d'’]+)"
_TOTAL = re.compile(r"(?:Ziffer|Ziff\.|chiffre|cifra)\s*200\b[^\n]*?" + _NUM, re.IGNORECASE)
_NORMAL = re.compile(r"(?:Ziffer|Ziff\.|chiffre|cifra)\s*30[23]\b[^\n]*?(\d+(?:\.\d+)?)\s*%[^\n]*?" + _NUM
                     + r"[^\n]*?" + _NUM, re.IGNORECASE)
TOLERANCE = Decimal("0.01")  # 1 % des Umsatzes: Abgrenzungen und Rundungen


def _amount(text: str) -> Decimal:
    return Decimal(re.sub(r"['’]", "", text))


def _chf(value: Decimal) -> str:
    return format_value("betrag", ("CHF", value))


def _vat_docs(room: DataRoom) -> list[Document]:
    return [d for d in room.documents if d.index and _DOC.search(d.title) and years_in(d.title)]


def check_vat(room: DataRoom) -> list[Flag]:
    flags: list[Flag] = []
    statement = _latest_statement(room)
    for doc in _vat_docs(room):
        year = years_in(doc.title)[0]
        totals, ev = [], []
        for p, text in enumerate(doc.pages, 1):
            for m in _TOTAL.finditer(text):
                totals.append(_amount(m.group(1)))
                ev.append(_evidence(doc, p, m.start(1), m.end(1)))
            for m in _NORMAL.finditer(text):
                rate, base, tax = Decimal(m.group(1)), _amount(m.group(2)), _amount(m.group(3))
                expected = (base * rate / 100).quantize(Decimal(1))
                if abs(expected - tax) > 5:
                    flags.append(Flag(WARNUNG, "MWST", f"Steuer nicht nachvollziehbar ({doc.label}, S. {p})",
                                      f"{rate} % von {_chf(base)} ergibt {_chf(expected)}, deklariert sind {_chf(tax)}.",
                                      [_evidence(doc, p, m.start(3), m.end(3))], [doc.index]))
        if not totals:
            continue
        declared = sum(totals, Decimal(0))
        if not statement or statement[1] != year or "umsatz" not in statement[2]:
            flags.append(Flag(HINWEIS, "MWST", f"Deklarierter Umsatz {year}: {_chf(declared)}",
                              f"Summe der Ziffer 200 aus {len(totals)} Abrechnungen ({doc.label}). Keine Jahresrechnung "
                              f"{year} zum Abgleich gefunden.", ev))
            continue
        revenue, rdoc, rpage, cell = statement[2]["umsatz"]
        ev.append(_evidence(rdoc, rpage, cell.fact.start, cell.fact.end))
        gap = revenue - declared
        basis = (f"Ziffer 200 der {len(totals)} Abrechnungen {year} ergibt {_chf(declared)} ({doc.label}), die "
                 f"Jahresrechnung zeigt Nettoerlöse von {_chf(revenue)} ({rdoc.label}).")
        if len(totals) < 4:
            flags.append(Flag(WARNUNG, "MWST", f"Nur {len(totals)} von 4 MWST-Abrechnungen {year} im Datenraum",
                              basis + " Die fehlenden Quartale nachreichen lassen.", ev, [doc.index]))
        elif revenue and abs(gap) / revenue > TOLERANCE:
            share = abs(gap) / revenue * 100
            if gap > 0:
                text = (f"{basis} Es fehlen {_chf(gap)} ({share:.1f} %). Sind sie nicht durch Abgrenzungen, "
                        "Erlösminderungen oder Umsätze ohne Steuer (Ziffer 200 umfasst auch diese) erklärt, droht eine "
                        f"Nachsteuer von bis zu {_chf((gap * Decimal('0.081')).quantize(Decimal(1)))} (8.1 %) "
                        "plus Verzugszins (Art. 87 MWSTG). Die ESTV kann fünf Jahre zurück nachfordern (Art. 42 "
                        "MWSTG). Umsatzabstimmung vom Verkäufer verlangen; Mängel sind nach Art. 72 MWSTG zu korrigieren.")
                title = f"Umsatzabstimmung {year}: {_chf(gap)} weniger deklariert als verbucht"
            else:
                text = (f"{basis} Deklariert sind {_chf(-gap)} ({share:.1f} %) mehr als verbucht. Das kann an "
                        "Anzahlungen oder Umsätzen ausserhalb der Nettoerlöse liegen, oder an zu tief ausgewiesenen "
                        "Erlösen in der Jahresrechnung. Abstimmung verlangen.")
                title = f"Umsatzabstimmung {year}: {_chf(-gap)} mehr deklariert als verbucht"
            flags.append(Flag(WARNUNG, "MWST", title, text, ev, [doc.index, rdoc.index]))
        else:
            flags.append(Flag(OK, "MWST", f"Umsatzabstimmung {year} stimmt",
                              f"{basis} Differenz {_chf(abs(gap))}, unter 1 %.", ev))
    return flags
