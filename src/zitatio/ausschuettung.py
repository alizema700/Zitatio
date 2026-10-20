"""Beschlossene Dividenden gegen die Bilanz und die Verrechnungssteuer.

- Dividenden dürfen nur aus dem Bilanzgewinn und aus frei verfügbaren Reserven ausgerichtet werden (Art. 675
  Abs. 2 OR). Grobe Obergrenze: Eigenkapital minus Aktienkapital minus gesetzliche Reserven; der Teil der
  gesetzlichen Reserven über der Hälfte des Aktienkapitals ist ausschüttbar (Art. 671 Abs. 2, 672 Abs. 2 OR).
  Zu Unrecht bezogene Dividenden können zurückgefordert werden (Art. 678 OR).
- Auf jede Dividende fallen 35 % Verrechnungssteuer an, abzurechnen mit Formular 103 innert 30 Tagen (Art. 4 und
  16 VStG), im Meldeverfahren mit Formular 106. Fehlt die Abrechnung im Datenraum, nachfragen.
"""

from __future__ import annotations

import re
from decimal import Decimal

from .dataroom import DataRoom
from .facts import AMOUNT, extract_facts, format_value
from .netdebt import _sentences
from .swiss import HINWEIS, WARNUNG, Flag, _latest_statement
from .tables import years_in
from .verify import _evidence

_DIVIDEND = re.compile(r"dividende|gewinnausschüttung|dividendo|distribution d'un dividende", re.I)
_DECIDED = re.compile(r"beschlo|beschlie|genehmig|décid|approuv|delibera|approva", re.I)
_FOR_YEAR = re.compile(r"(?:geschäftsjahr|bilanzgewinn|jahresgewinn|exercice|esercizio)\s+(\d{4})", re.I)
_VST_RETURN = re.compile(r"formular\s*10[36]|formulaire\s*10[36]|modulo\s*10[36]|verrechnungssteuer-?(?:abrechnung|deklaration)"
                         r"|décompte de l'impôt anticipé", re.I)


def _chf(x: Decimal) -> str:
    return format_value("betrag", ("CHF", x))


def check_dividends(room: DataRoom) -> list[Flag]:
    flags, found = [], []
    for doc in room.documents:
        if doc.index is None:
            continue
        for page_no, start, sentence in _sentences(doc):
            if not (_DIVIDEND.search(sentence) and _DECIDED.search(sentence)):
                continue
            amounts = [f for f in extract_facts(sentence) if f.kind == AMOUNT and f.value[0] == "CHF"]
            if not amounts:
                continue
            year = _FOR_YEAR.search(sentence)
            if year:
                year = int(year.group(1))
            else:
                dated = re.search(r"\b\d{1,2}\.\s?\d{1,2}\.\s?(\d{4})\b|\b(20\d{2})\b", sentence)
                title_years = years_in(doc.title)
                year = int(dated.group(1) or dated.group(2)) - 1 if dated else (title_years[0] - 1 if title_years else None)
            ev = _evidence(doc, page_no, start + amounts[0].start, start + amounts[0].end)
            found.append((doc, amounts[0].value[1], year, ev))

    for doc, amount, year, ev in found:
        statement = _latest_statement(room, year) if year else None
        if not statement:
            continue
        sdoc, _, v = statement
        if "aktienkapital" not in v:
            continue
        equity, capital = v["eigenkapital"][0], v["aktienkapital"][0]
        reserves = sum((v[k][0] for k in ("kapitalreserve", "gewinnreserve") if k in v), Decimal(0))
        strict = equity - capital - reserves
        loose = equity - capital - min(reserves, capital / 2)
        basis = (f"Dividende {_chf(amount)} ({doc.label}); Bilanz {year} ({sdoc.label}): Eigenkapital {_chf(equity)}, "
                 f"Aktienkapital {_chf(capital)}" + (f", gesetzliche Reserven {_chf(reserves)}" if reserves else "") + ".")
        sev = [ev] + [_evidence(d, p, c.fact.start, c.fact.end) for key, (_, d, p, c) in v.items()
                      if key in ("eigenkapital", "aktienkapital", "kapitalreserve", "gewinnreserve")]
        if amount > loose:
            flags.append(Flag(
                WARNUNG, "Ausschüttung", f"Dividende {_chf(amount)} über dem ausschüttbaren Eigenkapital {year}",
                f"{basis} Ausschüttbar sind höchstens {_chf(max(loose, Decimal(0)))} (Art. 675 Abs. 2 OR). Zu Unrecht "
                "bezogene Dividenden können zurückgefordert werden (Art. 678 OR); der Verwaltungsrat haftet (Art. 754 OR). "
                "Falls ein Zwischenabschluss vorliegt (Art. 675a OR), diesen verlangen.", sev, [doc.index]))
        elif amount > strict:
            flags.append(Flag(
                HINWEIS, "Ausschüttung", f"Dividende {_chf(amount)} greift gesetzliche Reserven an",
                f"{basis} Über das freie Eigenkapital von {_chf(max(strict, Decimal(0)))} hinaus ist nur der Teil der "
                "gesetzlichen Reserven ausschüttbar, der die Hälfte des Aktienkapitals übersteigt (Art. 671 Abs. 2, "
                "672 Abs. 2 OR). Beschluss der Generalversammlung und Revisionsbestätigung prüfen.", sev, [doc.index]))

    if found and not any(_VST_RETURN.search(t) for d in room.documents if d.index for t in d.pages):
        doc, amount, _, ev = found[0]
        total = sum((a for _, a, _, _ in found), Decimal(0))
        flags.append(Flag(
            HINWEIS, "Ausschüttung", "Verrechnungssteuer-Abrechnung zur Dividende fehlt im Datenraum",
            f"Beschlossene Dividenden von {_chf(total)} ({', '.join(sorted({d.label for d, *_ in found}))}). Darauf fallen "
            f"35 % Verrechnungssteuer an ({_chf(total * Decimal('0.35'))}), abzurechnen innert 30 Tagen mit Formular 103 "
            "oder im Meldeverfahren mit Formular 106 (Art. 16 VStG). Abrechnung und Zahlungsbeleg nachfordern.",
            [e for *_, e in found], sorted({d.index for d, *_ in found})))
    return flags
