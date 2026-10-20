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


# --- Steuerbarer Reingewinn gegen Jahresgewinn ---------------------------------------

_TAXABLE = re.compile(r"steuerbare[rn]?\s+reingewinn[^\n]*?" + _NUM, re.IGNORECASE)
_ASSESSMENT = re.compile(r"veranlagung|taxation|tassazione", re.IGNORECASE)


def _profit(room: DataRoom, year: int):
    """Jahresgewinn laut Jahresrechnung dieses Jahres (oder Vorjahresspalte der nächsten)."""
    from .tables import doc_cells

    for doc in sorted(room.documents, key=lambda d: years_in(d.title)[:1] != [year]):
        if not doc.index or not re.search(r"jahresrechnung|jahresabschluss", doc.title, re.I):
            continue
        for p in range(1, len(doc.pages) + 1):
            for cell in doc_cells(doc, p):
                if cell.year == year and re.match(r"(?:jahresgewinn|jahresergebnis|reingewinn)", cell.label, re.I):
                    return cell.fact.value[1], doc, p, cell
    return None


def check_taxable_profit(room: DataRoom) -> list[Flag]:
    """Massgeblichkeit: Der steuerbare Reingewinn folgt dem handelsrechtlichen Jahresgewinn (Art. 58 DBG).
    Steuern sind abziehbarer Aufwand (Art. 59 Abs. 1 lit. a DBG). Eine grosse Lücke heisst Aufrechnungen der
    Steuerbehörde (etwa nicht anerkannter Aufwand oder geldwerte Leistungen) oder Abzüge (Verlustvortrag)."""
    flags = []
    for doc in room.documents:
        if not doc.index or not _ASSESSMENT.search(doc.title) or not years_in(doc.title):
            continue
        year = years_in(doc.title)[0]
        for p, text in enumerate(doc.pages, 1):
            m = _TAXABLE.search(text)
            if not m:
                continue
            taxable = _amount(m.group(1))
            found = _profit(room, year)
            if not found or not found[0]:
                break
            profit, pdoc, ppage, cell = found
            ev = [_evidence(doc, p, m.start(1), m.end(1)), _evidence(pdoc, ppage, cell.fact.start, cell.fact.end)]
            diff = taxable - profit
            share = diff / abs(profit) * 100
            basis = (f"Steuerbarer Reingewinn {year} {_chf(taxable)} ({doc.label}), Jahresgewinn laut Jahresrechnung "
                     f"{_chf(profit)} ({pdoc.label}): {'+' if diff >= 0 else '−'}{_chf(abs(diff))} ({share:+.1f} %).")
            if share > 10:
                flags.append(Flag(HINWEIS, "Steuern", f"Aufrechnungen {year}: steuerbarer Gewinn {share:.0f} % über Jahresgewinn",
                                  basis + " Der steuerbare Gewinn folgt dem Jahresgewinn (Art. 58 DBG); die Differenz sind "
                                  "Aufrechnungen der Steuerbehörde. Aufstellung verlangen: Betreffen sie geldwerte "
                                  "Leistungen an Aktionäre, fällt auch Verrechnungssteuer an.", ev, [doc.index]))
            elif share < -10:
                flags.append(Flag(HINWEIS, "Steuern", f"Steuerbarer Gewinn {year} {abs(share):.0f} % unter Jahresgewinn",
                                  basis + " Abzüge wie Verlustvorträge (Art. 67 DBG) oder Beteiligungsabzug erklären das "
                                  "oft. Verlustvorträge sind beim Kauf ein Wert und gehen bei Mantelhandel verloren.", ev))
            else:
                flags.append(Flag(OK, "Steuern", f"Steuerbarer Gewinn {year} passt zum Jahresgewinn", basis, ev))
            break
    return flags
