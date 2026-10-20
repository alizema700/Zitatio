"""Nachrechnen statt Fehlalarm: abgeleitete Werte und EBITDA-Bereinigungen.

Ein Bericht nennt oft Zahlen, die so in keinem Dokument stehen: Wachstum, Margen, Summen,
das bereinigte EBITDA. Zitatio rechnet sie aus geprüften Werten nach. Geht die Rechnung
auf, ist die Aussage geprüft; geht sie nicht auf, ist es eine Abweichung mit Rechenweg;
lässt sie sich nicht nachrechnen, bleibt die Aussage ungeprüft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

from .dataroom import DataRoom
from .facts import AMOUNT, PERCENT, Fact, format_value
from .tables import LABELS, doc_cells, metric_of, metrics_in, years_in
from .verify import Finding, Status, _evidence

_SHARE_RE = re.compile(r"\b(?:\w+-)?marge\b|\banteil\w*|\bquote\b|\bstehen für\b|\bmach\w* .{0,30}\baus\b", re.I)
_GROWTH_RE = re.compile(r"\bwachstum\w*|\bgewachsen\b|\bwuchs\b|\bgestiegen\b|\bstieg\b|\bzunahme\b|\bzugenommen\b"
                        r"|\brückgang\b|\bgesunken\b|\bsank\b|\babnahme\b|\bveränderung\b", re.I)
_DECLINE_RE = re.compile(r"\brückgang\b|\bgesunken\b|\bsank\b|\babnahme\b|\bminus\b", re.I)
_SUM_RE = re.compile(r"\binsgesamt\b|\bzusammen\b|\bgesamt\w*|\btotal\b|\bsumme\b", re.I)
# Kennzahlen, die gerechnet und nicht abgelesen werden; DD-Berichte schreiben sie oft englisch.
_RATIO_RE = re.compile(r"\bdurchschnitt\w*|\bverhältnis\w*|\brendite\b|\bumschlag\w*|\bmargin\b|\bratio\b|\bgrowth\b"
                       r"|\bchange\b|\baverage\b|\bcagr\b|\bturnover\b|\bless\b|\s\+\s"
                       r"|free cash flow|working capital|umlaufvermögen", re.I)
_DERIVED_RE = re.compile(f"{_SHARE_RE.pattern}|{_GROWTH_RE.pattern}|{_SUM_RE.pattern}|{_RATIO_RE.pattern}"
                         "|\\bentspricht\\b", re.I)
_ADDBACK_SECTION_RE = re.compile(r"bereinig|add-?back|normalis|adjust|quality of earnings|\bqoe\b|sondereffekt", re.I)
_NEGATIVE_RE = re.compile(r"\b(?:abzüglich|abzug|minus|reduziert|vermindert|negativ\w*|abgezogen)\b|[−–-]\s*CHF", re.I)


def _chf(value: Decimal, currency: str = "CHF") -> str:
    return format_value(AMOUNT, (currency, value.quantize(Decimal(1))))


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'))} %"


def _tolerance(fact: Fact) -> Decimal:
    if fact.kind == PERCENT:
        step = fact.precision or Decimal(1)
        return step / 2 + Decimal("0.0001")
    return (fact.precision or Decimal(0)) / 2


def _found_amount(f: Finding) -> Fact | None:
    """Der erste Betrag einer Aussage, wenn er im Datenraum belegt ist."""
    if f.status not in (Status.GEPRUEFT, Status.FALSCHE_FUNDSTELLE, Status.WIDERSPRUCH):
        return None
    return next((x for x in f.claim.facts if x.kind == AMOUNT), None)


# --- EBITDA-Bereinigungen -----------------------------------------------------

@dataclass
class AddbackCheck:
    section: str
    base: Finding
    items: list[tuple[Finding, Decimal]]  # Aussage und Betrag mit Vorzeichen
    total: Finding
    expected: Decimal
    stated: Decimal
    ok: bool
    unsupported: list[Finding] = field(default_factory=list)

    @property
    def share(self) -> Decimal | None:
        """Anteil der Bereinigungen am bereinigten EBITDA in Prozent."""
        if not self.stated:
            return None
        return sum((v for _, v in self.items), Decimal(0)) / self.stated * 100

    @property
    def summary(self) -> str:
        base = next(x for x in self.base.claim.facts if x.kind == AMOUNT).value[1]
        parts = [f"EBITDA {_chf(base)}"] + [
            f"{'−' if v < 0 else '+'} {_chf(abs(v))} (Aussage {f.claim.number})" for f, v in self.items
        ]
        return " ".join(parts) + f" = {_chf(self.expected)}"


def _amount(f: Finding) -> Fact | None:
    return next((x for x in f.claim.facts if x.kind == AMOUNT), None)


def check_addbacks(findings: list[Finding]) -> list[AddbackCheck]:
    checks = []
    sections: dict[str, list[Finding]] = {}
    for f in findings:
        sections.setdefault(f.claim.section, []).append(f)
    for section, items in sections.items():
        if not _ADDBACK_SECTION_RE.search(section):
            continue
        base_i = next((i for i, f in enumerate(items) if _amount(f) and
                       "ebitda" in {m[0] for m in metrics_in(f.claim.clean_text)} and
                       "ebitda_bereinigt" not in {m[0] for m in metrics_in(f.claim.clean_text)}), None)
        total_i = next((i for i, f in enumerate(items) if _amount(f) and
                        "ebitda_bereinigt" in {m[0] for m in metrics_in(f.claim.clean_text)}), None)
        if base_i is None or total_i is None or total_i <= base_i + 1:
            continue
        base, total = items[base_i], items[total_i]
        adds = []
        for f in items[base_i + 1 : total_i]:
            fact = _amount(f)
            if fact is None:
                continue
            value = fact.value[1]
            adds.append((f, -value if _NEGATIVE_RE.search(f.claim.clean_text) else value))
        if not adds:
            continue
        base_fact, total_fact = _amount(base), _amount(total)
        expected = base_fact.value[1] + sum(v for _, v in adds)
        stated = total_fact.value[1]
        tol = _tolerance(total_fact) + _tolerance(base_fact) + sum(_tolerance(_amount(f)) for f, _ in adds)
        unsupported = [f for f, _ in adds if f.status is not Status.GEPRUEFT]
        checks.append(AddbackCheck(section, base, adds, total, expected, stated, abs(expected - stated) <= tol, unsupported))
    return checks


def apply_addbacks(checks: list[AddbackCheck]) -> None:
    for c in checks:
        for f in c.unsupported:
            if f.status is Status.OHNE_BELEG:
                f.reasons.insert(0, "Bereinigung ohne Beleg: Jede Bereinigung des EBITDA braucht eine Fundstelle im Datenraum.")
        total = c.total
        total.method = "Nachgerechnet"
        if not c.ok:
            diff = c.stated - c.expected
            total.status = Status.ABWEICHUNG
            total.reasons = [f"Nachgerechnet: {c.summary}. Der Bericht nennt {_chf(c.stated)} "
                             f"(Differenz {'+' if diff > 0 else '−'}{_chf(abs(diff))})."]
            continue
        line = f"Nachgerechnet: {c.summary}; das passt zu {_chf(c.stated)}."
        if total.status is Status.GEPRUEFT:
            total.reasons.append(line)
            continue
        base_ok = c.base.status in (Status.GEPRUEFT, Status.WIDERSPRUCH)
        if c.unsupported or not base_ok:
            open_ = [f.claim.number for f in c.unsupported] + ([] if base_ok else [c.base.claim.number])
            total.status = Status.OHNE_BELEG
            total.reasons = [line + " Die Rechnung geht auf, aber nicht jeder Summand ist belegt "
                             f"(Aussage {', '.join(map(str, sorted(open_)))})."]
        else:
            total.status = Status.GEPRUEFT
            total.reasons = [line + " Alle Summanden sind belegt."]
        total.missing = []


# --- Abgeleitete Werte --------------------------------------------------------

def _page_metric_values(f: Finding, room: DataRoom, metric: str) -> dict[int, tuple]:
    """Jahreswerte einer Grösse auf den zitierten Seiten: {Jahr: (Wert, Dokument, Seite, Zelle)}."""
    out = {}
    for c in f.claim.citations:
        doc = room.get(c.index)
        if doc is None:
            continue
        pages = range(c.page_from, (c.page_to or c.page_from) + 1) if c.page_from else range(1, len(doc.pages) + 1)
        for p in pages:
            if not 1 <= p <= len(doc.pages):
                continue
            for cell in doc_cells(doc, p):
                if cell.metric == metric and cell.tabular and cell.year and cell.period == str(cell.year):
                    out.setdefault(cell.year, (cell.fact.value[1], doc, p, cell))
    return out


def _recompute_percent(f: Finding, fact: Fact, previous: list[Finding], room: DataRoom):
    """(passt, Rechenweg, Belege) oder None, wenn nichts nachzurechnen ist."""
    text = f.claim.clean_text
    years = years_in(text)
    tries = []
    m = re.search(r"\b(\w+)-?marge\b", text, re.I)
    if m or _SHARE_RE.search(text):
        numerator = metric_of(m.group(1)) if m else None
        numerator = numerator or next((k for k, _, _ in metrics_in(text) if k != "umsatz"), None)
        if numerator:
            num, den = _page_metric_values(f, room, numerator), _page_metric_values(f, room, "umsatz")
            for y in sorted(set(num) & set(den), reverse=True):
                if years and y not in years:
                    continue
                value = num[y][0] / den[y][0] * 100
                tries.append((value, f"{LABELS[numerator]} {y} {_chf(num[y][0])} / Umsatz {y} {_chf(den[y][0])} = {_pct(value)}",
                              [num[y], den[y]]))
    if _GROWTH_RE.search(text):
        metric = next((k for k, _, _ in metrics_in(text)), None)
        for prev in reversed(previous[-3:]):
            metric = metric or next((k for k, _, _ in metrics_in(prev.claim.clean_text)), None)
        if metric:
            values = _page_metric_values(f, room, metric)
            for y in sorted(values, reverse=True):
                if y - 1 not in values or (years and y not in years):
                    continue
                now, before = values[y][0], values[y - 1][0]
                value = (now / before - 1) * 100
                if _DECLINE_RE.search(text):
                    value = -value
                tries.append((value, f"{LABELS[metric]} {y} {_chf(now)} / {y - 1} {_chf(before)} − 1 = {_pct(value)}",
                              [values[y], values[y - 1]]))
    if not tries:
        return None
    for value, how, cells in tries:
        if abs(value - fact.value) <= _tolerance(fact):
            return True, how, cells
    value, how, cells = tries[0]
    return False, how, cells


def _recompute_sum(f: Finding, fact: Fact, previous: list[Finding]):
    if not _SUM_RE.search(f.claim.clean_text):
        return None
    pool = [(p, a) for p in previous if (a := _found_amount(p)) and a.value[0] == fact.value[0]][-12:]
    tol = _tolerance(fact)
    for size in range(2, min(len(pool), 6) + 1):
        for combo in combinations(pool, size):
            total = sum(a.value[1] for _, a in combo)
            if abs(total - fact.value[1]) <= tol:
                how = " + ".join(f"{_chf(a.value[1])} (Aussage {p.claim.number})" for p, a in combo)
                return True, f"{how} = {_chf(total)}", []
    return False, "", []


def apply_derived(findings: list[Finding], room: DataRoom, skip: set[int] = frozenset()) -> None:
    """Abweichungen, die abgeleitete Werte sind, nachrechnen."""
    for i, f in enumerate(findings):
        if f.status is not Status.ABWEICHUNG or not f.missing or f.claim.number in skip:
            continue
        if not _DERIVED_RE.search(f.claim.clean_text):
            continue
        previous = [p for p in findings[:i] if p.claim.section == f.claim.section]
        results = []
        for fact in f.missing:
            if fact.kind == PERCENT:
                results.append((fact, _recompute_percent(f, fact, previous, room)))
            elif fact.kind == AMOUNT:
                results.append((fact, _recompute_sum(f, fact, previous)))
            else:
                results.append((fact, None))
        if all(r and r[0] for _, r in results):
            f.status, f.method = Status.GEPRUEFT, "Nachgerechnet"
            f.reasons = [f"Abgeleiteter Wert, nachgerechnet: {how}." for _, (_, how, _) in results]
            for _, (_, _, cells) in results:
                for _, doc, p, cell in cells:
                    f.evidence.append(_evidence(doc, p, cell.fact.start, cell.fact.end))
            f.missing = []
        elif any(r and not r[0] and r[1] for _, r in results):
            f.method = "Nachgerechnet"
            f.reasons = [
                f"Nachgerechnet: {how}; der Bericht nennt {fact.display()}." if r and not r[0] and how
                else f"{fact.display()} steht nicht an der Fundstelle."
                for fact, r in results for how in [r[1] if r else ""]
            ]
            for _, r in results:
                for _, doc, p, cell in (r[2] if r else []):
                    f.evidence.append(_evidence(doc, p, cell.fact.start, cell.fact.end))
        else:
            f.status = Status.UNGEPRUEFT
            values = ", ".join(fact.display() for fact in f.missing)
            f.reasons = [f"{values}: abgeleiteter Wert, der so nicht an der Fundstelle steht und sich nicht "
                         "automatisch nachrechnen lässt. Bitte manuell prüfen."]
