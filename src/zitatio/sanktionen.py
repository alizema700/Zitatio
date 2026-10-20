"""Gegenparteien gegen eine Sanktionsliste prüfen.

Wer mit einer Person oder Firma auf der Sanktionsliste des SECO Geschäfte macht, verstösst gegen die Verordnungen
zum Embargogesetz (EmbG, SR 946.231). Zitatio sammelt die Namen im Datenraum (Aktionäre, Zeichnungsberechtigte,
Firmen in Verträgen und Unterlagen) und gleicht sie mit einer Liste ab, die das Team mitgibt: die Gesamtliste des
SECO als XML (sesam.search.admin.ch), eine CSV-Datei oder ein Name pro Zeile. Zitatio lädt nichts aus dem Internet.

Ein Treffer ist ein Hinweis auf eine Namensgleichheit, kein Beweis: Geburtsdatum, Sitz oder Registernummer klären.
"""

from __future__ import annotations

import re
import unicodedata
from xml.etree import ElementTree as ET

from .dataroom import DataRoom
from .swiss import _HOLDER, OK, WARNUNG, Flag, signatories
from .verify import _evidence

_ENTITY = re.compile(r"\b((?:(?:[A-ZÄÖÜ][\w&'’-]*|[A-Z][a-z]{0,2}\.) ){1,4}(?:AG|SA|GmbH|Sàrl|Sagl|Ltd\.?|LLC|Inc\.?|S\.p\.A\.|SE|PLC|"
                     r"Holding|Stiftung|Fondation|LLP|JSC|OOO|OAO|PJSC))\b")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in re.findall(r"[a-z0-9]+", _fold(name)) if t not in {"dr", "prof", "von", "van", "de"})


def read_list(data: bytes, suffix: str) -> list[str]:
    """Namen aus der SECO-XML (je <name> die Teile zusammen), aus CSV (erste Spalte) oder Text."""
    if suffix == ".xml":
        root = ET.fromstring(data)
        names = []
        for el in root.iter():
            if el.tag.split("}")[-1] != "name":
                continue
            parts = [v.text.strip() for v in el.iter() if v.tag.split("}")[-1] == "value" and v.text and v.text.strip()]
            if parts:
                names.append(" ".join(parts))
        return list(dict.fromkeys(names))
    text = data.decode("utf-8-sig", errors="replace")
    out = []
    for line in text.splitlines():
        cell = re.split(r"[;,\t]", line)[0].strip().strip('"')
        if len(cell) >= 4 and not cell.lower() in ("name", "namen", "firma"):
            out.append(cell)
    return out


def parties(room: DataRoom) -> dict[frozenset, tuple[str, object]]:
    """Namen im Datenraum mit einer Fundstelle: {Tokens: (Name, Evidence)}."""
    found: dict[frozenset, tuple[str, object]] = {}
    for s in signatories(room):
        text = s.doc.pages[s.page - 1]
        end = re.match(r"[^,\n]+(?:,[^,\n]+)?", text[s.start :])  # "Fässler, Luca"
        found.setdefault(_tokens(s.name), (s.name, _evidence(s.doc, s.page, s.start, s.start + (end.end() if end else 1))))
    for doc in room.documents:
        if doc.index is None:
            continue
        for p, text in enumerate(doc.pages, 1):
            for m in _HOLDER.finditer(text):
                found.setdefault(_tokens(m.group(1)), (m.group(1).strip(), _evidence(doc, p, m.start(1), m.end(1))))
            for m in _ENTITY.finditer(text):
                name = m.group(1).strip()
                toks = _tokens(name)
                if len(toks) >= 2:
                    found.setdefault(toks, (name, _evidence(doc, p, m.start(1), m.end(1))))
    return found


def check_sanctions(room: DataRoom, names: list[str], list_name: str = "Sanktionsliste") -> list[Flag]:
    listed = {}
    for n in names:
        toks = _tokens(n)
        if len(toks) >= 2:  # ein einzelnes Wort trifft zu viel
            listed.setdefault(toks, n)
    hits = []
    for toks, (name, ev) in parties(room).items():
        if toks in listed:
            hits.append((name, listed[toks], ev))
    if not hits:
        return [Flag(OK, "Sanktionen", f"Kein Name auf der {list_name}",
                     f"{len(parties(room))} Namen aus dem Datenraum gegen {len(listed)} Einträge geprüft.")]
    return [Flag(WARNUNG, "Sanktionen", f"{name} steht auf der {list_name}",
                 f"«{name}» im Datenraum entspricht dem Eintrag «{entry}». Vor jedem weiteren Schritt mit Geburtsdatum, "
                 "Sitz oder Registernummer klären; Geschäfte mit sanktionierten Personen verbieten die Verordnungen zum "
                 "Embargogesetz (EmbG).", [ev] if ev else [], [ev.doc_label.removeprefix("DR ")] if ev else [])
            for name, entry, ev in hits]


def attach(run, data: bytes, filename: str) -> None:
    """Sanktionsabgleich an einen fertigen Lauf hängen (CLI und Weboberfläche)."""
    from pathlib import Path

    names = read_list(data, Path(filename).suffix.lower())
    run.flags = sorted(run.flags + check_sanctions(run.room, names, f"Sanktionsliste {Path(filename).name}"),
                       key=lambda fl: ("warnung", "hinweis", "ok").index(fl.level))
