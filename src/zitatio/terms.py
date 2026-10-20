"""Laufzeiten, Kündigungsfristen und die Closing-Liste.

Aus jedem Vertrag des Registers liest Zitatio Beginn, Ende, Kündigungsfrist und jährliches Volumen
mit Seite. Daraus entsteht die Liste, die vor dem Signing auf den Tisch gehört:

- Verträge mit Kontrollwechselklausel: Gegenpartei kann beim Closing kündigen; Zustimmung einholen.
  Mit dem Volumen ergibt sich, wie viel Umsatz daran hängt.
- Verträge, die abgelaufen sind oder in den nächsten 18 Monaten enden: Verlängerung klären.
- Verträge mit Zustimmung zur Abtretung: nur beim Asset Deal relevant.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .clauses import ContractEntry
from .facts import AMOUNT, DATE, DURATION, extract_facts
from .verify import Evidence, _evidence

_END = re.compile(r"endet am|fest (?:abgeschlossen )?bis|läuft bis|befristet bis|laufzeit bis|gültig bis"
                  r"|prend fin le|expire le|jusqu'au|conclu pour une durée déterminée jusqu|termine il|scade il|fino al", re.I)
_START = re.compile(r"beginnt am|tritt am|in kraft|ab\b|entre en vigueur|débute le|dès le|entra in vigore|inizia il|a partire dal", re.I)
_TERM = re.compile(r"laufzeit|durée|durata", re.I)
_NOTICE = re.compile(r"künd\w*|résili\w*|préavis|disdett\w*|disdire|preavviso", re.I)
_VOLUME = re.compile(r"volumen|umsatz|volume|chiffre d'affaires|fatturato", re.I)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")


@dataclass
class Terms:
    entry: ContractEntry
    start: dt.date | None = None
    end: dt.date | None = None
    notice: tuple[int, str] | None = None
    volume: Decimal | None = None
    evidence: dict[str, Evidence] = field(default_factory=dict)

    @property
    def doc(self):
        return self.entry.doc

    def notice_text(self) -> str:
        return f"{self.notice[0]} {self.notice[1]}" if self.notice else ""


def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return dt.date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


def contract_terms(entry: ContractEntry) -> Terms:
    t = Terms(entry)
    doc = entry.doc
    for page_no, text in enumerate(doc.pages, 1):
        flat = text.replace("\n", " ")
        for m in _SENTENCE.finditer(flat):
            sentence = m.group(0)
            facts = extract_facts(sentence)
            dates = [f for f in facts if f.kind == DATE]
            durations = [f for f in facts if f.kind == DURATION]
            amounts = [f for f in facts if f.kind == AMOUNT]

            def keep(key: str, fact) -> None:
                t.evidence.setdefault(key, _evidence(doc, page_no, m.start() + fact.start, m.start() + fact.end))

            if dates and _END.search(sentence) and t.end is None:
                end = next((f for f in dates if f.start > _END.search(sentence).start()), dates[-1])
                t.end = end.value
                keep("ende", end)
            if dates and _START.search(sentence) and t.start is None:
                t.start = dates[0].value
                keep("beginn", dates[0])
            if (t.end is None and _TERM.search(sentence) and durations and t.start is not None
                    and durations[0].value[1] == "Monate"):
                t.end = _add_months(t.start, durations[0].value[0]) - dt.timedelta(days=1)
                keep("ende", durations[0])
            if (t.notice is None and durations and _NOTICE.search(sentence)
                    and not re.search(r"kontrollwechsel|change of control|changement de contrôle|cambiamento di controllo",
                                      sentence, re.I)):
                t.notice = durations[0].value
                keep("kuendigung", durations[0])
            if t.volume is None and amounts and _VOLUME.search(sentence) and amounts[0].value[0] == "CHF":
                t.volume = amounts[0].value[1]
                keep("volumen", amounts[0])
    return t


# --- Closing-Liste --------------------------------------------------------------

@dataclass
class ClosingItem:
    kind: str  # kontrollwechsel, laufzeit, abtretung
    terms: Terms
    text: str
    evidence: list[Evidence]


def closing_list(register: list[ContractEntry], today: dt.date | None = None,
                 horizon_months: int = 18) -> tuple[list[Terms], list[ClosingItem]]:
    today = today or dt.date.today()
    horizon = _add_months(today, horizon_months)
    terms = [contract_terms(e) for e in register]
    items = []
    for t in terms:
        coc = [c for c in t.entry.clauses if c.kind == "kontrollwechsel" and c.present]
        if coc:
            c = coc[0]
            items.append(ClosingItem("kontrollwechsel", t,
                                     f"Gegenpartei kann beim Kontrollwechsel kündigen (S. {c.page}). Zustimmung oder "
                                     "Verzicht vor dem Closing einholen.",
                                     [_evidence(c.doc, c.page, c.start, c.end)]))
        if t.end and t.end < today:
            items.append(ClosingItem("laufzeit", t, f"Abgelaufen am {t.end:%d.%m.%Y}. Klären, ob der Vertrag "
                                     "verlängert wurde oder ohne Grundlage weiterläuft.", [t.evidence["ende"]]))
        elif t.end and t.end <= horizon:
            items.append(ClosingItem("laufzeit", t, f"Endet am {t.end:%d.%m.%Y}, in weniger als {horizon_months} "
                                     "Monaten. Verlängerung klären.", [t.evidence["ende"]]))
    return terms, items


def revenue_at_risk(items: list[ClosingItem]) -> Decimal:
    seen, total = set(), Decimal(0)
    for i in items:
        if i.kind == "kontrollwechsel" and i.terms.volume and id(i.terms) not in seen:
            seen.add(id(i.terms))
            total += i.terms.volume
    return total


def _n(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", "'")
