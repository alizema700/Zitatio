"""Was sich im Datenraum seit dem letzten Stand geändert hat.

Der Verkäufer lädt laufend nach und ersetzt Dokumente. Das Deal-Team muss wissen, was neu ist, was fehlt und welche
Zahlen sich in einem ersetzten Dokument geändert haben, ohne alles neu zu lesen. Zitatio vergleicht zwei Exporte
nach Indexnummer und Prüfsumme und nennt pro geändertem Dokument die Seiten und Werte, die anders sind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dataroom import DataRoom, Document
from .facts import extract_facts


@dataclass
class DocChange:
    kind: str  # neu, entfernt, geändert
    label: str
    title: str
    pages: list[int] = field(default_factory=list)  # geänderte Seiten (neue Nummerierung)
    removed: list[str] = field(default_factory=list)  # Werte, die nicht mehr vorkommen
    added: list[str] = field(default_factory=list)  # Werte, die neu vorkommen


def _key(doc: Document) -> str:
    return doc.index or doc.name


def _values(text: str) -> list[str]:
    return [f.display() for f in extract_facts(text)]


def compare_rooms(old: DataRoom, new: DataRoom) -> list[DocChange]:
    before = {_key(d): d for d in old.documents}
    after = {_key(d): d for d in new.documents}
    changes = []
    for key, doc in after.items():
        prev = before.get(key)
        if prev is None:
            changes.append(DocChange("neu", doc.label, doc.title, list(range(1, len(doc.pages) + 1))))
            continue
        if prev.sha256 == doc.sha256 or prev.pages == doc.pages:
            continue
        pages = [i + 1 for i in range(max(len(doc.pages), len(prev.pages)))
                 if (doc.pages[i] if i < len(doc.pages) else None) != (prev.pages[i] if i < len(prev.pages) else None)]
        old_values = _values("\n".join(prev.pages))
        new_values = _values("\n".join(doc.pages))
        removed = [v for v in dict.fromkeys(old_values) if v not in new_values]
        added = [v for v in dict.fromkeys(new_values) if v not in old_values]
        changes.append(DocChange("geändert", doc.label, doc.title, pages, removed, added))
    for key, doc in before.items():
        if key not in after:
            changes.append(DocChange("entfernt", doc.label, doc.title))
    order = {"geändert": 0, "neu": 1, "entfernt": 2}
    return sorted(changes, key=lambda c: (order[c.kind], c.label))


def describe(c: DocChange) -> str:
    if c.kind == "neu":
        return f"Neu: {c.label} {c.title} ({len(c.pages)} Seite{'n' if len(c.pages) != 1 else ''})."
    if c.kind == "entfernt":
        return f"Entfernt: {c.label} {c.title}."
    pages = ", ".join(map(str, c.pages[:10])) + (" …" if len(c.pages) > 10 else "")
    parts = []
    if c.removed:
        parts.append("nicht mehr da: " + ", ".join(c.removed[:6]) + (" …" if len(c.removed) > 6 else ""))
    if c.added:
        parts.append("neu: " + ", ".join(c.added[:6]) + (" …" if len(c.added) > 6 else ""))
    values = (" Werte " + "; ".join(parts) + ".") if parts else ""
    return f"Geändert: {c.label} {c.title}, S. {pages}.{values}"
