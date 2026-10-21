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

from .clauses import _CONTRACT_TITLE, ContractEntry
from .facts import AMOUNT, DATE, DURATION, extract_facts
from .verify import Evidence, _evidence

_END = re.compile(r"endet am|fest (?:abgeschlossen )?bis|läuft bis|befristet bis|laufzeit bis|gültig bis"
                  r"|prend fin le|expire le|jusqu'au|conclu pour une durée déterminée jusqu|termine il|scade il|fino al", re.I)
_START = re.compile(r"beginnt am|tritt am|in kraft|ab\b|entre en vigueur|débute le|dès le|entra in vigore|inizia il|a partire dal", re.I)
_TERM = re.compile(r"laufzeit|durée|durata", re.I)
_NOTICE = re.compile(r"künd\w*|résili\w*|préavis|disdett\w*|disdire|preavviso", re.I)
_VOLUME = re.compile(r"volumen|umsatz|volume|chiffre d'affaires|fatturato", re.I)
_ANY_TERM = re.compile("|".join(rx.pattern for rx in (_END, _START, _TERM, _NOTICE, _VOLUME)), re.I)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")


@dataclass
class Terms:
    entry: ContractEntry
    start: dt.date | None = None
    end: dt.date | None = None
    notice: tuple[int, str] | None = None
    volume: Decimal | None = None
    notice_to: str | None = None  # Kündigung auf das Ende eines "jahr", "quartal" oder "monat"
    after_fixed: bool = False  # ordentlich kündbar erst nach Ablauf der festen Dauer
    evidence: dict[str, Evidence] = field(default_factory=dict)

    @property
    def doc(self):
        return self.entry.doc

    def notice_text(self) -> str:
        if not self.notice:
            return ""
        to = {"jahr": " auf Jahresende", "quartal": " auf Quartalsende", "monat": " auf Monatsende"}.get(self.notice_to, "")
        return f"{self.notice[0]} {self.notice[1]}{to}"

    def earliest_exit(self, today: dt.date) -> dt.date | None:
        """Frühestes Datum, auf das der Vertrag ordentlich endet, wenn heute gekündigt wird."""
        if self.end and self.end < today:
            return self.end  # abgelaufen: das Volumen hängt schon jetzt an einer Verlängerung
        if self.notice is None or self.after_fixed:
            return self.end
        n, unit = self.notice
        months = {"Monate": n, "Jahre": 12 * n}.get(unit)
        d = _add_months(today, months) if months is not None else today + dt.timedelta(days=n * (7 if unit == "Wochen" else 1))
        if self.notice_to == "jahr":
            d = dt.date(d.year, 12, 31)
        elif self.notice_to == "quartal":
            q_end = ((d.month - 1) // 3 + 1) * 3
            d = _add_months(dt.date(d.year, q_end, 1), 1) - dt.timedelta(days=1)
        elif self.notice_to == "monat":
            d = _add_months(dt.date(d.year, d.month, 1), 1) - dt.timedelta(days=1)
        return min(d, self.end) if self.end and self.end >= today else d


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
            if not _ANY_TERM.search(sentence):
                continue
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
                if re.search(r"ende (?:eines|des) (?:kalender)?jahres|jahresende|fin d'une année|fin de l'année"
                             r"|fine dell'anno|fine di un anno", sentence, re.I):
                    t.notice_to = "jahr"
                elif re.search(r"quartal|trimestre", sentence, re.I):
                    t.notice_to = "quartal"
                elif re.search(r"ende (?:eines|des) monats|monatsende|fin d'un mois|fine del mese", sentence, re.I):
                    t.notice_to = "monat"
                t.after_fixed = bool(re.search(r"nach ablauf|après l'expiration|dopo la scadenza", sentence, re.I))
            if (t.volume is None and amounts and _VOLUME.search(sentence) and amounts[0].value[0] == "CHF"
                    and not re.search(r"mindestabnahme|abnahmeverpflichtung", sentence, re.I)):
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
    terms = [contract_terms(e) if _CONTRACT_TITLE.search(e.doc.title) else Terms(e) for e in register]
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


def exit_profile(terms: list[Terms], today: dt.date | None = None) -> list[tuple[int, Decimal, list[Terms]]]:
    """Jährliches Vertragsvolumen nach dem Jahr, in dem es frühestens wegfallen kann."""
    today = today or dt.date.today()
    by_year: dict[int, list[Terms]] = {}
    for t in terms:
        exit_date = t.earliest_exit(today) if t.volume else None
        if exit_date:
            by_year.setdefault(exit_date.year, []).append(t)
    return [(year, sum((t.volume for t in ts), Decimal(0)), ts) for year, ts in sorted(by_year.items())]


def revenue_at_risk(items: list[ClosingItem]) -> Decimal:
    seen, total = set(), Decimal(0)
    for i in items:
        if i.kind == "kontrollwechsel" and i.terms.volume and id(i.terms) not in seen:
            seen.add(id(i.terms))
            total += i.terms.volume
    return total


def _n(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", "'")
