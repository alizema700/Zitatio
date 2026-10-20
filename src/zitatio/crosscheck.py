"""Querprüfung im Datenraum: nennen zwei Dokumente für dieselbe Grösse verschiedene Werte?

Falsche Finanzangaben des Verkäufers sind der grösste Treiber von W&I-Schäden. Sie zeigen
sich oft als Widerspruch innerhalb des Datenraums: Die Vorjahresspalte der neuen
Jahresrechnung weicht von der alten ab, die Management Accounts summieren sich auf einen
anderen Umsatz als der Abschluss, Handelsregister und Statuten nennen ein anderes Kapital.
Verglichen werden nur Tabellenzeilen mit bekannter Grösse und Periode; Ist und Plan getrennt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dataroom import DataRoom, Document
from .facts import Fact
from .tables import LABELS, TIMELESS, Cell, doc_cells
from .verify import Evidence, Finding, Status, _evidence


@dataclass
class Sighting:
    doc: Document
    page: int
    cell: Cell
    evidence: Evidence

    @property
    def where(self) -> str:
        return f"{self.doc.label}, S. {self.page}"

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.doc.name, self.page, self.cell.fact.start)


@dataclass
class Conflict:
    metric: str
    period: str | None
    plan: bool
    groups: list[list[Sighting]] = field(default_factory=list)  # je Gruppe übereinstimmende Werte

    @property
    def title(self) -> str:
        label = LABELS[self.metric]
        label = label[0].upper() + label[1:]
        return label + (f" {self.period}" if self.period else "") + (" (Plan)" if self.plan else "")

    @property
    def sightings(self) -> list[Sighting]:
        return [s for g in self.groups for s in g]

    def describe(self) -> str:
        parts = []
        for group in self.groups:
            places = [s.where for s in group]
            value = group[0].cell.fact.display()
            parts.append(f"{', '.join(dict.fromkeys(places))}: {value}")
        return f"{self.title}: " + "; ".join(parts) + "."


def same_value(a: Fact, b: Fact) -> bool:
    """Gleich bis auf Rundung: "31'862" TCHF und CHF 31'862'415 widersprechen sich nicht."""
    return bool(a.match(b) or b.match(a))


def find_conflicts(room: DataRoom) -> list[Conflict]:
    buckets: dict[tuple, list[Sighting]] = {}
    for doc in room.documents:
        if doc.index is None:
            continue
        for page in range(1, len(doc.pages) + 1):
            for cell in doc_cells(doc, page):
                if not (cell.metric and cell.tabular):
                    continue
                timeless = cell.metric in TIMELESS
                if not timeless and cell.period is None:
                    continue
                period = None if timeless else cell.period
                key = (cell.metric, period, cell.plan, cell.fact.value[0])
                ev = _evidence(doc, page, cell.fact.start, cell.fact.end)
                buckets.setdefault(key, []).append(Sighting(doc, page, cell, ev))

    conflicts = []
    for (metric, period, plan, _), sightings in buckets.items():
        # Ein Dokument mit mehreren Werten für dieselbe Grösse und Periode (Segmente, Quartale, Teilsummen in
        # einem US-Jahresbericht) sagt nicht, welcher Wert "der" Wert ist: es zählt dann nicht mit.
        per_doc: dict[str, list[Sighting]] = {}
        for s in sightings:
            per_doc.setdefault(s.doc.name, []).append(s)
        sightings = [s for ss in per_doc.values() if all(same_value(ss[0].cell.fact, o.cell.fact) for o in ss)
                     for s in ss]
        groups: list[list[Sighting]] = []
        for s in sightings:
            group = next((g for g in groups if same_value(g[0].cell.fact, s.cell.fact)), None)
            if group is None:
                groups.append([s])
            else:
                group.append(s)
        docs = {s.doc.name for s in sightings}
        # Mehrere Werte in nur einem Dokument sind oft Segmente oder Teilsummen: nicht melden.
        if len(groups) > 1 and len(docs) > 1:
            conflicts.append(Conflict(metric, period, plan, groups))
    conflicts.sort(key=lambda c: (c.plan, c.metric, c.period or ""))
    return conflicts


def apply_conflicts(findings: list[Finding], conflicts: list[Conflict]) -> None:
    """Aussagen, deren Wert im Datenraum umstritten ist, sind nicht einfach "Geprüft"."""
    by_key = {s.key: c for c in conflicts for s in c.sightings}
    for f in findings:
        hit = next((by_key[h] for h in f.hits if h in by_key), None)
        if hit is None:
            continue
        own = set(f.hits)
        others = [s for s in hit.sightings if s.key not in own and not any(
            same_value(s.cell.fact, o.cell.fact) for o in hit.sightings if o.key in own)]
        f.reasons.append(
            "Der Datenraum widerspricht sich: " + hit.describe()
            + " Welcher Wert stimmt, muss geklärt werden."
        )
        seen = set()
        for s in others:
            if s.where not in seen:
                seen.add(s.where)
                f.evidence.append(s.evidence)
        if f.status is Status.GEPRUEFT:
            f.status = Status.WIDERSPRUCH
