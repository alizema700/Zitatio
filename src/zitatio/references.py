"""Nachträge und Side Letters, die erwähnt werden, aber im Datenraum fehlen.

Ein Vertrag gilt so, wie er zuletzt geändert wurde. Erwähnt ein Dokument einen Nachtrag, eine
Zusatzvereinbarung oder einen Side Letter, der nicht im Datenraum liegt, kann jede Zahl aus dem
Grundvertrag überholt sein. Zitatio sucht solche Verweise und prüft, ob ein passendes Dokument da ist.
"""

from __future__ import annotations

import re

from .clauses import _CONTRACT_TITLE
from .dataroom import DataRoom
from .swiss import WARNUNG, Flag
from .verify import _evidence

_AMENDMENT = re.compile(
    r"\b(?:nachtrag|zusatzvereinbarung|änderungsvereinbarung|side[- ]letter|addendum|amendment|avenant|"
    r"accord complémentaire|lettre annexe|aggiunta|accordo aggiuntivo|emendamento)\w*"
    r"(?:\s+(?:nr\.?|no\.?|n°)\s*\d+)?",
    re.IGNORECASE,
)
_TITLE = re.compile(r"nachtrag|zusatz|änderung|side[- ]letter|addendum|amendment|avenant|complémentaire|aggiunt|emendament",
                    re.IGNORECASE)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\s?\d))+(?:[.!?]|$)")  # "Nachtrag Nr. 1" beendet keinen Satz
# "Änderungen dieses Vertrags bedürfen der Schriftform" ist eine Klausel, kein Verweis auf einen Nachtrag
_GENERIC = re.compile(r"bedürfen|schriftform|nur gültig|sont valables|devono essere", re.IGNORECASE)


def missing_amendments(room: DataRoom) -> list[Flag]:
    amendments = [d for d in room.documents if d.index and _TITLE.search(d.title)]
    flags = []
    for doc in room.documents:
        # Nur Verträge: Jahresberichte erwähnen "Amendment No. 3" zu Exhibits, das ist kein fehlender Nachtrag
        if doc.index is None or _TITLE.search(doc.title) or not _CONTRACT_TITLE.search(doc.title):
            continue
        seen = set()
        for page_no, text in enumerate(doc.pages, 1):
            flat = text.replace("\n", " ")
            for m in _SENTENCE.finditer(flat):
                sentence = m.group(0)
                hit = _AMENDMENT.search(sentence)
                if not hit or _GENERIC.search(sentence):
                    continue
                name = re.sub(r"\s+", " ", hit.group(0)).strip()
                if name.lower() in seen:
                    continue
                seen.add(name.lower())
                # Liegt ein Nachtrag zum selben Dokument vor (Indexnummer darunter oder gleicher Titelanfang)?
                if any(a.index.startswith(doc.index + ".") or _same_contract(a.title, doc.title) for a in amendments):
                    continue
                flags.append(Flag(WARNUNG, "Verweise", f"{doc.label}: {name} fehlt im Datenraum",
                                  f"{doc.label}, S. {page_no} erwähnt «{_trim(sentence)}» Ein solches Dokument liegt "
                                  "nicht im Datenraum. Werte aus dem Grundvertrag können überholt sein; beim Verkäufer "
                                  "anfordern.",
                                  [_evidence(doc, page_no, m.start() + hit.start(), m.start() + hit.end())], [doc.index]))
    return flags


def _same_contract(amendment_title: str, title: str) -> bool:
    words = {w for w in re.findall(r"\w{5,}", title.lower())}
    return len(words & set(re.findall(r"\w{5,}", amendment_title.lower()))) >= 2


def _trim(text: str, width: int = 200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"
