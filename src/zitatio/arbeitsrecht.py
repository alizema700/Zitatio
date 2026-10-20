"""Arbeitsverträge und Personalreglement gegen zwingendes Arbeitsrecht (OR).

Zwei Punkte, die in einer Due Diligence oft übersehen werden:

- Konkurrenzverbot länger als drei Jahre: Es darf "nur unter besonderen Umständen" drei Jahre überschreiten
  (Art. 340a Abs. 1 OR); das Gericht kann es einschränken. Es fällt zudem dahin, wenn der Arbeitgeber ohne
  begründeten Anlass kündigt (Art. 340c Abs. 2 OR). Wer nach dem Kauf umstrukturiert, verliert den Schutz.
- Ferien unter dem Minimum von vier Wochen (Art. 329a Abs. 1 OR, zwingend nach Art. 362 OR): Die fehlenden
  Tage sind nachzuzahlen, für alle Mitarbeitenden und bis fünf Jahre zurück (Art. 128 Ziff. 3 OR).
"""

from __future__ import annotations

import re

from .dataroom import DataRoom
from .swiss import HINWEIS, WARNUNG, Flag
from .verify import _evidence

_EMPLOYMENT = re.compile(r"arbeitsvertr[aä]g|personalreglement|mitarbeiterreglement|contrat de travail|"
                         r"règlement du personnel|contratto di lavoro|regolamento del personale", re.I)
_NON_COMPETE = re.compile(r"konkurrenzverbot|wettbewerbsverbot|non-?concurrence|divieto di concorrenza", re.I)
_WORDS = {"ein": 1, "einem": 1, "eines": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
          "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "uno": 1, "due": 2, "tre": 3,
          "quattro": 4, "cinque": 5}
_DURATION = re.compile(r"\b(\d{1,2}|" + "|".join(_WORDS) + r")\s+(jahre?n?s?|monate?n?|ans?|années?|mois|anni|mesi)\b",
                       re.I)
_HOLIDAYS = re.compile(r"(\d{1,2})\s+(?:ferientage|arbeitstage ferien|tage ferien|jours de vacances|giorni di vacanza)"
                       r"|(\d)\s+wochen ferien|(\d)\s+semaines de vacances|(\d)\s+settimane di vacanza", re.I)


def _months(number: str, unit: str) -> int:
    n = int(number) if number.isdigit() else _WORDS[number.lower()]
    return n if unit.lower().startswith(("monat", "mois", "mes")) else 12 * n


def _sentence(text: str, pos: int) -> tuple[int, int]:
    start = max(text.rfind(".", 0, pos), text.rfind("\n", 0, pos)) + 1
    ends = [i for i in (text.find(".", pos), text.find("\n", pos)) if i != -1]
    return start, min(ends) if ends else len(text)


def check_employment(room: DataRoom) -> list[Flag]:
    flags = []
    for doc in room.documents:
        if doc.index is None or not (_EMPLOYMENT.search(doc.title) or any(_EMPLOYMENT.search(t[:300]) for t in doc.pages)):
            continue
        for p, text in enumerate(doc.pages, 1):
            for m in _NON_COMPETE.finditer(text):
                start, end = _sentence(text, m.start())
                durations = [d for d in _DURATION.finditer(text, start, end)]
                if not durations:
                    continue
                d = max(durations, key=lambda d: _months(d.group(1), d.group(2)))
                if _months(d.group(1), d.group(2)) <= 36:
                    continue
                flags.append(Flag(
                    HINWEIS, "Arbeitsrecht", f"Konkurrenzverbot über drei Jahre in {doc.label}",
                    f"{doc.label} {doc.title}, S. {p}: «{text[start:end].strip()}». Länger als drei Jahre ist ein "
                    "Konkurrenzverbot nur unter besonderen Umständen gültig (Art. 340a Abs. 1 OR); das Gericht kann es "
                    "kürzen. Kündigt die Gesellschaft ohne begründeten Anlass, fällt es ganz dahin (Art. 340c Abs. 2 "
                    "OR). Nicht als Schutz für den Käufer einrechnen.",
                    [_evidence(doc, p, d.start(), d.end())], [doc.index]))
            for m in _HOLIDAYS.finditer(text):
                days = int(m.group(1)) if m.group(1) else 5 * int(next(g for g in m.groups()[1:] if g))
                if days >= 20:
                    continue
                flags.append(Flag(
                    WARNUNG, "Arbeitsrecht", f"Ferienanspruch unter dem gesetzlichen Minimum in {doc.label}",
                    f"{doc.label} {doc.title}, S. {p} nennt {days} Ferientage; zwingend sind mindestens vier Wochen "
                    "(20 Arbeitstage bei der Fünftagewoche), für Mitarbeitende bis 20 Jahre fünf Wochen (Art. 329a "
                    "OR, Art. 362 OR). Die fehlenden Tage schuldet die Gesellschaft allen Betroffenen, bis fünf Jahre "
                    "zurück (Art. 128 Ziff. 3 OR). Betrag schätzen und freistellen lassen.",
                    [_evidence(doc, p, m.start(), m.end())], [doc.index]))
    return flags
