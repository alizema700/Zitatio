"""Benchmark mit künstlich eingebauten Fehlern.

Aus jeder Zeile des Datenraums, die einen prüfbaren Wert enthält, wird eine
korrekt belegte Aussage gebaut. Dazu kommen Varianten mit genau einem Fehler
(falscher Wert, falsche Seite, fehlendes Dokument, fehlende Fundstelle).
Gemessen wird, wie oft der Prüfer den erwarteten Status vergibt.

Das misst die Regelprüfung gegen bekannte Fehlerarten. Es ersetzt keinen
Benchmark mit echten, von Menschen geschriebenen DD-Berichten.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .dataroom import DataRoom, Document
from .facts import AMOUNT, DATE, DURATION, PERCENT, UID, Fact, extract_facts, format_value
from .report import parse_report, split_sentences
from .verify import ModelVerifier, Status, verify_claim

KORREKT, SCHREIBWEISE, WERT, SEITE, DOKUMENT, OHNE = (
    "korrekt", "andere Schreibweise", "falscher Wert", "falsche Seite", "fehlendes Dokument", "ohne Fundstelle"
)
EXPECTED = {
    KORREKT: Status.GEPRUEFT,
    SCHREIBWEISE: Status.GEPRUEFT,
    WERT: Status.ABWEICHUNG,
    SEITE: Status.FALSCHE_FUNDSTELLE,
    DOKUMENT: Status.QUELLE_FEHLT,
    OHNE: Status.OHNE_BELEG,
}
MISSING_INDEX = "99.9"


@dataclass
class Case:
    kind: str
    text: str
    expected: Status
    actual: Status | None = None

    @property
    def ok(self) -> bool:
        return self.actual is self.expected


@dataclass
class Result:
    cases: list[Case] = field(default_factory=list)

    def by_kind(self) -> dict[str, tuple[int, int]]:
        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for c in self.cases:
            totals[c.kind][0] += c.ok
            totals[c.kind][1] += 1
        return {k: (v[0], v[1]) for k, v in totals.items()}

    @property
    def accuracy(self) -> float:
        return sum(c.ok for c in self.cases) / len(self.cases) if self.cases else 0.0

    def confusion(self) -> Counter:
        return Counter((c.expected, c.actual) for c in self.cases if not c.ok)


def _all_values(room: DataRoom) -> set:
    return {(f.kind, f.value) for d in room.documents for p in d.pages for f in extract_facts(p)}


def _mutate(fact: Fact, taken: set) -> str | None:
    """Plausibler falscher Wert, der nirgends im Datenraum vorkommt."""
    for step in range(1, 30):
        if fact.kind == AMOUNT:
            cur, amount = fact.value
            digits = f"{int(amount)}"
            i = 1 + (step - 1) % (len(digits) - 1) if len(digits) > 1 else 0
            bump = 1 + (step - 1) // max(1, len(digits) - 1)
            new = (cur, Decimal(digits[:i] + str((int(digits[i]) + bump) % 10) + digits[i + 1 :]))
        elif fact.kind == DATE:
            new = fact.value.replace(year=fact.value.year + step) if fact.value.month != 2 else fact.value + dt.timedelta(days=365 * step)
        elif fact.kind == PERCENT:
            new = fact.value + Decimal("0.5") * step
        elif fact.kind == DURATION:
            new = (fact.value[0] + step, fact.value[1])
        elif fact.kind == UID:
            return fact.value[:-1] + str((int(fact.value[-1]) + step) % 10)
        else:
            return None
        if (fact.kind, new) not in taken:
            return format_value(fact.kind, new)
    return None


_MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
                "Oktober", "November", "Dezember"]


def _respell(fact: Fact) -> str | None:
    """Derselbe Wert in einer anderen, im DD-Alltag üblichen Schreibweise."""
    if fact.kind == AMOUNT:
        cur, amount = fact.value
        if amount >= 1_000_000 and amount % 10_000 == 0:
            return f"{cur} {(amount / 1_000_000).normalize():f} Mio."
        if amount >= 1000 and amount % 1000 == 0:
            return f"T{cur} {int(amount / 1000):,}".replace(",", "'")
        return f"{int(amount):,} {cur}".replace(",", "'") if amount == int(amount) else None
    if fact.kind == DATE:
        return f"{fact.value.day}. {_MONTH_NAMES[fact.value.month - 1]} {fact.value.year}"
    if fact.kind == PERCENT:
        return f"{fact.value:f}".replace(".", ",") + " Prozent"
    return None


def _transpose(fact: Fact, taken: set) -> str | None:
    """Zahlendreher wie 18'450'000 -> 18'540'000, der häufigste Tippfehler."""
    if fact.kind != AMOUNT:
        return None
    cur, amount = fact.value
    digits = f"{int(amount)}"
    for i in range(len(digits) - 1):
        if digits[i] != digits[i + 1]:
            swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
            new = (cur, Decimal(swapped))
            if not swapped.startswith("0") and (AMOUNT, new) not in taken:
                return format_value(AMOUNT, new)
    return None


def _citation(index: str, page: int) -> str:
    return f"[DR {index}, S. {page}]"


def build_cases(room: DataRoom) -> list[Case]:
    taken = _all_values(room)
    cases: list[Case] = []
    for doc in room.documents:
        if doc.index is None:
            continue
        for page_no, page in enumerate(doc.pages, start=1):
            for line in page.splitlines():
                for sentence in split_sentences(line.strip()):
                    cases.extend(_cases_for(sentence.rstrip(" ."), doc, page_no, taken))
    return cases


def _cases_for(sentence: str, doc: Document, page_no: int, taken: set) -> list[Case]:
    facts = extract_facts(sentence)
    if not facts:
        return []
    target = facts[-1]
    cite = _citation(doc.index, page_no)
    out = [Case(KORREKT, f"{sentence} {cite}.", EXPECTED[KORREKT]),
           Case(DOKUMENT, f"{sentence} {_citation(MISSING_INDEX, 1)}.", EXPECTED[DOKUMENT])]

    respelled = _respell(target)
    if respelled:
        variant = sentence[: target.start] + respelled + sentence[target.end :]
        out.append(Case(SCHREIBWEISE, f"{variant} {cite}.", EXPECTED[SCHREIBWEISE]))

    wrong = _transpose(target, taken) or _mutate(target, taken)
    if wrong:
        mutated = sentence[: target.start] + wrong + sentence[target.end :]
        out.append(Case(WERT, f"{mutated} {cite}.", EXPECTED[WERT]))

    out.append(Case(OHNE, f"{sentence}.", EXPECTED[OHNE]))

    for other in range(1, len(doc.pages) + 1):
        if other == page_no:
            continue
        page_values = {(f.kind, f.value) for f in extract_facts(doc.pages[other - 1])}
        if not any((f.kind, f.value) in page_values for f in facts):
            out.append(Case(SEITE, f"{sentence} {_citation(doc.index, other)}.", EXPECTED[SEITE]))
            break
    return out


def run_benchmark(room: DataRoom, model: ModelVerifier | None = None) -> Result:
    result = Result()
    for case in build_cases(room):
        claims = parse_report(case.text)
        if len(claims) != 1:
            continue
        case.actual = verify_claim(claims[0], room, model).status
        result.cases.append(case)
    return result
