"""Preisbrücke: was die Befunde für den Kaufpreis bedeuten.

Nennt der Bericht ein Multiple auf das (bereinigte) EBITDA, rechnet Zitatio den Unternehmenswert und
den Equity Value nach (Unternehmenswert minus Nettoverschuldung aus der Bilanz). Dann zeigt die Brücke,
wie sich die Befunde auf den Preis auswirken: Eine Bereinigung ohne Beleg fällt mal das Multiple weg,
schuldenähnliche Posten mindern den Equity Value Franken für Franken, Klagen stehen als Risiko daneben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .facts import AMOUNT
from .verify import Finding, Status

_MULTIPLE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:x\b|×|-?fache[sn]?\b|mal\b)", re.IGNORECASE)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")
_EBITDA = re.compile(r"ebitda", re.IGNORECASE)
_EV = re.compile(r"unternehmenswert|enterprise value|valeur d'entreprise|valore d'impresa", re.IGNORECASE)
_EQUITY = re.compile(r"equity value|eigenkapitalwert|kaufpreis für (?:die|das) aktien|wert der aktien"
                     r"|valeur des fonds propres|valore del capitale", re.IGNORECASE)


@dataclass
class Impact:
    label: str
    amount: Decimal  # Wirkung auf den Equity Value, negativ = tiefer
    basis: str
    href: str = ""


@dataclass
class Valuation:
    multiple: Decimal
    multiple_text: str  # Satz im Bericht, der das Multiple nennt
    ebitda: Decimal  # bereinigtes EBITDA laut Bericht
    net_debt: Decimal | None
    year: int | None
    impacts: list[Impact] = field(default_factory=list)
    risks: list[Impact] = field(default_factory=list)

    @property
    def ev(self) -> Decimal:
        return self.multiple * self.ebitda

    @property
    def equity(self) -> Decimal | None:
        return None if self.net_debt is None else self.ev - self.net_debt

    @property
    def checked_equity(self) -> Decimal | None:
        if self.equity is None:
            return None
        return self.equity + sum((i.amount for i in self.impacts), Decimal(0))


def _amounts(f: Finding):
    return [x for x in f.claim.facts if x.kind == AMOUNT and x.value[0] == "CHF"]


def value_bridge(report_text: str, addbacks: list, debt) -> Valuation | None:
    claim = None
    # Im ganzen Bericht suchen: Ein Satz, der nur das Multiple nennt, ist keine prüfbare Aussage
    blocks = [b.replace("\n", " ") for b in re.split(r"\n\s*\n|\n(?=#)", report_text) if not b.lstrip().startswith("#")]
    for text in (m.group(0) for b in blocks for m in _SENTENCE.finditer(b)):
        m = _MULTIPLE.search(text)
        if m and _EBITDA.search(text) and (_EV.search(text) or re.search(r"multiple|bewert|évaluation|valutazione",
                                                                          text, re.IGNORECASE)):
            claim, multiple = text.strip(), Decimal(m.group(1).replace(",", "."))
            break
    if claim is None:
        return None
    check = addbacks[0] if addbacks else None
    if check is not None:
        ebitda = check.stated
    elif debt is not None and debt.ebitda:
        ebitda = debt.ebitda
    else:
        return None
    v = Valuation(multiple, claim, ebitda, debt.net_debt if debt is not None else None,
                  debt.year if debt is not None else None)
    if check is not None:
        for f, value in check.items:
            if any(f is u for u in check.unsupported):
                v.impacts.append(Impact(f"Bereinigung ohne Beleg (Aussage {f.claim.number})", -value * multiple,
                                        f"{_chf(value)} × {multiple}", f"#a{f.claim.number}"))
        if not check.ok:
            diff = check.expected - check.stated
            v.impacts.append(Impact("Bereinigtes EBITDA rechnet nicht", diff * multiple,
                                    f"{_chf(diff)} × {multiple}", "#bereinigungen"))
    if debt is not None:
        from .netdebt import AEHNLICH, EVENTUAL

        for i in debt.items:
            if i.kind == AEHNLICH:
                v.impacts.append(Impact(i.label, -i.amount, "schuldenähnlich, Franken für Franken",
                                        "#nettoverschuldung"))
            elif i.kind == EVENTUAL:
                v.risks.append(Impact(i.label, -i.amount, "Streitwert, nicht bilanziert", "#nettoverschuldung"))
    return v


def apply_valuation(findings: list[Finding], v: Valuation | None) -> None:
    """Aussagen zu Unternehmenswert und Equity Value nachrechnen."""
    if v is None:
        return
    open_basis = any(i.label.startswith("Bereinigung") for i in v.impacts)
    for f in findings:
        text = f.claim.clean_text
        amounts = _amounts(f)
        if len(amounts) < 1 or f.status in (Status.FALSCHE_FUNDSTELLE, Status.WIDERSPRUCH):
            continue
        if _EQUITY.search(text) and v.equity is not None:
            target, what = v.equity, (f"{_chf(v.ev)} Unternehmenswert − {_chf(v.net_debt)} Nettoverschuldung "
                                      f"{v.year} = {_chf(v.equity)}")
            fact = amounts[-1]
        elif _EV.search(text):
            target, what = v.ev, f"{v.multiple} × {_chf(v.ebitda)} bereinigtes EBITDA = {_chf(v.ev)}"
            fact = next((a for a in amounts if abs(a.value[1] - v.ev) < abs(a.value[1] - v.ebitda)), amounts[-1])
        else:
            continue
        tolerance = max(fact.precision or Decimal(1), abs(target) * Decimal("0.001"))
        f.method = "Nachgerechnet"
        if abs(fact.value[1] - target) > tolerance:
            f.status = Status.ABWEICHUNG
            f.reasons = [f"Nachgerechnet: {what}, nicht {fact.display()}."]
        elif open_basis:
            f.status = Status.OHNE_BELEG
            f.reasons = [f"Nachgerechnet: {what}; das passt. Das bereinigte EBITDA enthält aber eine Bereinigung "
                         "ohne Beleg, siehe Preisbrücke."]
        else:
            f.status = Status.GEPRUEFT
            f.reasons = [f"Nachgerechnet: {what}."]
        f.missing = []


def _chf(value: Decimal) -> str:
    if abs(value) >= 10**6:
        return f"CHF {value / 10**6:,.2f} Mio.".replace(",", "'")
    return f"CHF {value:,.0f}".replace(",", "'")
