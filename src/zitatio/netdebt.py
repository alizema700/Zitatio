"""Nettoverschuldung, schuldenähnliche Posten und Covenants.

Beim Kauf wird vom Unternehmenswert die Nettoverschuldung abgezogen, um den Preis für die Aktien zu
erhalten. Was als Schuld zählt, wird verhandelt: Neben Bankschulden und flüssigen Mitteln aus der
Bilanz sucht Zitatio schuldenähnliche Posten im Datenraum (Leasing, Verbindlichkeiten gegenüber der
Vorsorgeeinrichtung, beschlossene Dividenden) und Eventualverbindlichkeiten (Klagen). Steht im
Kreditvertrag ein Covenant "Nettoverschuldung höchstens x-mal EBITDA", wird er nachgerechnet.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .clauses import ContractEntry
from .dataroom import DataRoom, Document
from .facts import AMOUNT, extract_facts
from .swiss import OK, WARNUNG, Flag, _latest_statement
from .tables import doc_cells
from .verify import Evidence, Finding, Status, _evidence

FINANZ, AEHNLICH, EVENTUAL = "Finanzschuld", "schuldenähnlich", "Eventualverbindlichkeit"
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")


@dataclass
class Item:
    label: str
    amount: Decimal  # positiv = erhöht die Schuld, negativ = mindert sie (flüssige Mittel)
    kind: str
    evidence: list[Evidence]
    note: str = ""


@dataclass
class Covenant:
    limit: Decimal
    ratio: Decimal
    evidence: Evidence

    @property
    def ok(self) -> bool:
        return self.ratio <= self.limit


@dataclass
class NetDebt:
    year: int
    items: list[Item] = field(default_factory=list)
    ebitda: Decimal | None = None
    ebitda_evidence: Evidence | None = None
    covenant: Covenant | None = None

    @property
    def net_debt(self) -> Decimal:
        return sum((i.amount for i in self.items if i.kind == FINANZ), Decimal(0))

    @property
    def adjusted(self) -> Decimal:
        return self.net_debt + sum((i.amount for i in self.items if i.kind == AEHNLICH), Decimal(0))


def _sentences(doc: Document):
    for page_no, text in enumerate(doc.pages, 1):
        flat = text.replace("\n", " ")
        for m in _SENTENCE.finditer(flat):
            yield page_no, m.start(), m.group(0)


def _first_amount(doc: Document, rx: re.Pattern) -> tuple[Decimal, Evidence] | None:
    for page_no, start, sentence in _sentences(doc):
        if rx.search(sentence):
            amounts = [f for f in extract_facts(sentence) if f.kind == AMOUNT and f.value[0] == "CHF"]
            if amounts:
                f = amounts[0]
                return f.value[1], _evidence(doc, page_no, start + f.start, start + f.end)
    return None


def _months_between(a: dt.date, b: dt.date) -> int:
    return max(0, (b.year - a.year) * 12 + b.month - a.month)


def net_debt(room: DataRoom, register: list[ContractEntry] | None = None) -> NetDebt | None:
    latest = _latest_statement(room)
    if not latest:
        return None
    doc, year, _ = latest
    nd = NetDebt(year)
    found: dict[str, tuple[Decimal, Evidence, str]] = {}
    for p in range(1, len(doc.pages) + 1):
        for cell in doc_cells(doc, p):
            if cell.plan or cell.year not in (None, year):
                continue
            if cell.metric in ("finanzschulden", "fluessige_mittel", "ebitda") and cell.metric not in found:
                found[cell.metric] = (cell.fact.value[1], _evidence(doc, p, cell.fact.start, cell.fact.end), cell.label)
    if "finanzschulden" not in found and "fluessige_mittel" not in found:
        return None
    if "finanzschulden" in found:
        value, ev, label = found["finanzschulden"]
        nd.items.append(Item(label, value, FINANZ, [ev]))
    if "fluessige_mittel" in found:
        value, ev, label = found["fluessige_mittel"]
        nd.items.append(Item(label, -value, FINANZ, [ev]))
    if "ebitda" in found:
        nd.ebitda, nd.ebitda_evidence, _ = found["ebitda"]
    closing_date = dt.date(year, 12, 31)

    pension = _first_amount(doc, re.compile(r"verbindlichkeit\w*[^.]{0,40}vorsorge|vorsorge\w*[^.]{0,40}verbindlichkeit", re.I))
    if pension:
        nd.items.append(Item("Verbindlichkeiten gegenüber Vorsorgeeinrichtungen", pension[0], AEHNLICH, [pension[1]]))

    for d in room.documents:
        if d.index is None:
            continue
        if re.search(r"leasing", d.title, re.I):
            rate = _first_amount(d, re.compile(r"leasingrate|monatlich\w* rate", re.I))
            residual = _first_amount(d, re.compile(r"restwert", re.I))
            end = None
            if register:
                from .terms import contract_terms

                entry = next((e for e in register if e.doc is d), None)
                end = contract_terms(entry).end if entry else None
            if rate and end and end > closing_date:
                months = _months_between(closing_date, end)
                total = rate[0] * months + (residual[0] if residual else 0)
                evidence = [rate[1]] + ([residual[1]] if residual else [])
                nd.items.append(Item(f"Leasing {d.label} (geschätzt)", total, AEHNLICH, evidence,
                                     f"{months} Raten à CHF {rate[0]:,.0f} ab {closing_date:%d.%m.%Y}".replace(",", "'")
                                     + (" plus Restwert" if residual else "")))
        if re.search(r"klage|prozess|verfahren|rechtsstreit|litige|causa", d.title, re.I):
            claim = _first_amount(d, re.compile(r"fordert|forderung|streitwert|klagt", re.I))
            if claim:
                nd.items.append(Item(f"Klage {d.label}", claim[0], EVENTUAL, [claim[1]], "Streitwert, nicht bilanziert"))
        if re.search(r"protokoll", d.title, re.I):
            dividend = _first_amount(d, re.compile(r"dividende[^.]{0,80}beschlo|beschlie\w*[^.]{0,80}dividende", re.I))
            if dividend:
                nd.items.append(Item(f"Beschlossene Dividende {d.label}", dividend[0], AEHNLICH, [dividend[1]]))

        if nd.covenant is None and nd.ebitda:
            for page_no, start, sentence in _sentences(d):
                m = re.search(r"nettoverschuldung[^.]{0,60}?(\d+(?:[.,]\d+)?)\s*-?\s*(?:fache|x\b|mal)[^.]{0,30}ebitda",
                              sentence, re.I)
                if m:
                    limit = Decimal(m.group(1).replace(",", "."))
                    ratio = (nd.net_debt / nd.ebitda).quantize(Decimal("0.01"))
                    nd.covenant = Covenant(limit, ratio, _evidence(d, page_no, start + m.start(), start + m.end()))
                    break
    return nd


def netdebt_flags(nd: NetDebt | None) -> list[Flag]:
    if nd is None or nd.covenant is None:
        return []
    c = nd.covenant
    text = (f"Nettoverschuldung {_chf(nd.net_debt)} geteilt durch EBITDA {_chf(nd.ebitda)} ergibt {c.ratio}x; "
            f"der Kreditvertrag erlaubt höchstens {c.limit}x ({c.evidence.doc_label}, S. {c.evidence.page}).")
    evidence = [c.evidence] + [e for i in nd.items if i.kind == FINANZ for e in i.evidence]
    if c.ok:
        return [Flag(OK, "Covenant", f"Covenant eingehalten ({c.ratio}x von höchstens {c.limit}x)", text, evidence)]
    return [Flag(WARNUNG, "Covenant", f"Covenant verletzt ({c.ratio}x statt höchstens {c.limit}x)",
                 text + " Die Bank kann den Kredit kündigen.", evidence, [c.evidence.doc_label.removeprefix("DR ")])]


def apply_netdebt(findings: list[Finding], nd: NetDebt | None) -> None:
    """Aussagen zum Covenant und zur Nettoverschuldung mit der nachgerechneten Zahl prüfen."""
    if nd is None:
        return
    for f in findings:
        text = f.claim.clean_text.lower()
        if f.status not in (Status.UNGEPRUEFT, Status.OHNE_BELEG, Status.GEPRUEFT, Status.ABWEICHUNG):
            continue
        if (nd.covenant and f.status is not Status.ABWEICHUNG and "covenant" in text
                and re.search(r"eingehalten|erfüllt|respecté|rispettat", text)):
            c = nd.covenant
            f.evidence.append(c.evidence)
            f.method = "Nachgerechnet"
            if c.ok:
                f.status = Status.GEPRUEFT
                f.reasons = [f"Nachgerechnet: Nettoverschuldung / EBITDA = {c.ratio}x, erlaubt sind höchstens {c.limit}x."]
            else:
                f.status = Status.ABWEICHUNG
                f.reasons = [f"Nachgerechnet: Nettoverschuldung / EBITDA = {c.ratio}x, erlaubt sind höchstens "
                             f"{c.limit}x. Der Covenant ist verletzt."]
            continue
        if "nettoverschuldung" in text and "covenant" not in text and f.status is not Status.GEPRUEFT:
            amounts = [x for x in f.claim.facts if x.kind == AMOUNT]
            if len(amounts) != 1:
                continue
            fact = amounts[0]
            tolerance = max(fact.precision or Decimal(1), abs(nd.net_debt) * Decimal("0.005"))
            f.method = "Nachgerechnet"
            f.evidence.extend(e for i in nd.items if i.kind == FINANZ for e in i.evidence)
            parts = " ".join(f"{'−' if i.amount < 0 else '+'} {_chf(abs(i.amount))} ({i.label})"
                             for i in nd.items if i.kind == FINANZ).lstrip("+ ")
            if abs(fact.value[1] - nd.net_debt) <= tolerance:
                f.status = Status.GEPRUEFT
                f.reasons = [f"Nachgerechnet aus der Bilanz {nd.year}: {parts} = {_chf(nd.net_debt)}."]
            else:
                # Steht der Wert auch sonst nicht im Datenraum, bleibt es eine Abweichung, jetzt mit der Rechnung
                f.status = Status.ABWEICHUNG
                f.reasons = [f"Die Bilanz {nd.year} ergibt {parts} = {_chf(nd.net_debt)}, nicht {fact.display()}."]


def _chf(value: Decimal) -> str:
    return f"CHF {value:,.0f}".replace(",", "'")
