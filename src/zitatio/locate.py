"""Belegsuche: die Fundstelle einer Aussage im ganzen Datenraum finden.

Nicht jedes Dokument zitiert seine Quellen. Ein Information Memorandum, eine Management-Präsentation oder ein
Bericht mit Fundstellen nur pro Kapitel nennt Zahlen ohne Seite. Zitatio sucht dann die Seiten, deren Wörter am
besten zur Aussage passen (BM25 über alle Seiten), und prüft auf diesen Seiten die Werte wie bei einer zitierten
Aussage. Gefunden ist ein Wert nur, wenn er auf einer passenden Seite in passender Umgebung steht.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .dataroom import DataRoom, Document

_FOLD = str.maketrans("äöüàâéèêëîïôûùç", "aouaaeeeeiiouuc")
_STOP = {"der", "die", "das", "und", "oder", "von", "mit", "für", "auf", "den", "dem", "des", "ein", "eine", "einer",
         "ist", "sind", "wird", "werden", "wurde", "beträgt", "betrug", "betragen", "per", "bis", "aus", "nach",
         "über", "zum", "zur", "bei", "als", "auch", "nicht", "sich", "seit", "damit", "rund", "total", "insgesamt",
         "gesellschaft", "seite", "les", "des", "une", "est", "del", "della", "che"}


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-zäöüàâéèêëîïôûùç]{3,}", text.lower())
    return [w.translate(_FOLD)[:6] for w in words if w not in _STOP]


class PageIndex:
    """BM25 über alle Seiten der Dokumente mit Indexnummer."""

    def __init__(self, room: DataRoom, k1: float = 1.2, b: float = 0.75):
        self.pages: list[tuple[Document, int]] = []
        self.tf: list[Counter] = []
        df: Counter = Counter()
        for doc in room.documents:
            if doc.index is None:
                continue
            title = _terms(doc.title)
            for p, text in enumerate(doc.pages, 1):
                terms = Counter(_terms(text)) + Counter(title)  # der Titel zählt auf jeder Seite
                self.pages.append((doc, p))
                self.tf.append(terms)
                df.update(terms.keys())
        n = len(self.pages) or 1
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.lengths = [sum(tf.values()) for tf in self.tf]
        self.avg = (sum(self.lengths) / n) or 1
        self.k1, self.b = k1, b

    def search(self, text: str, k: int = 8, only: set[str] | None = None) -> list[tuple[Document, int, float]]:
        """Beste Seiten zur Anfrage; only: nur in diesen Dateien suchen."""
        query = set(_terms(text)) & self.idf.keys()
        scored = []
        for i, tf in enumerate(self.tf):
            if only is not None and self.pages[i][0].name not in only:
                continue
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg)
            for t in query:
                f = tf.get(t)
                if f:
                    score += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [(*self.pages[i], s) for s, i in scored[:k]]


def page_index(room: DataRoom) -> PageIndex:
    cached = getattr(room, "_page_index", None)
    if cached is None or cached[0] != len(room.documents):
        cached = (len(room.documents), PageIndex(room))
        object.__setattr__(room, "_page_index", cached)
    return cached[1]
