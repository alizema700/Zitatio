"""Datenschutz im Datenraum: Personendaten, die vor der Weitergabe geschwärzt gehören.

Ein Datenraum geht an Käufer, die noch nicht unterschrieben haben. Das Datenschutzgesetz (DSG) erlaubt die
Bekanntgabe nur, soweit sie für die Prüfung nötig ist (Art. 6 Abs. 2 und 3 DSG). Zitatio sucht zwei Arten von
Daten, die fast nie nötig sind:

- AHV-Nummern (756.xxxx.xxxx.xx, mit Prüfziffer): Die systematische Verwendung ist ausserhalb der
  Sozialversicherung nur erlaubt, wo ein Gesetz es vorsieht (Art. 153b ff. AHVG).
- Gesundheitsdaten zu einzelnen Personen (Krankheit, Diagnose, Arztzeugnis, IV): besonders schützenswerte
  Personendaten nach Art. 5 lit. c Ziff. 2 DSG.

Gemeldet wird pro Dokument, mit Fundstelle. Das schützt den Verkäufer (Haftung) und den Käufer, der die Daten
nicht haben will.
"""

from __future__ import annotations

import re

from .dataroom import DataRoom
from .swiss import WARNUNG, Flag
from .verify import _evidence

_AHV = re.compile(r"\b756[.\s]?(\d{4})[.\s]?(\d{4})[.\s]?(\d{2})\b")
_HEALTH = re.compile(r"krankheitsbedingt\w*|\bdiagnose\w*|arztzeugnis\w*|ärztlich\w* attest\w*|\bIV-(?:Rente|Anmeldung)"
                     r"|invalidenversicherung|burn-?out|psychiatr\w*|schwangerschaft\w*|certificat médical"
                     r"|arrêt maladie|certificato medico", re.IGNORECASE)
# Gesundheitsdaten in Verträgen und Policen sind meist allgemein ("bei Krankheit"); gemeldet wird nur mit Person.
_PERSON = re.compile(r"\b(?:Herr|Frau|Hr\.|Fr\.|Mitarbeite\w+|Arbeitnehme\w+|M\.|Mme)\s+(?:Dr\.\s+)?[A-ZÄÖÜ][a-zäöüé]+")


def _ahv_valid(digits: str) -> bool:
    """EAN-13-Prüfziffer der AHV-Nummer."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def check_privacy(room: DataRoom) -> list[Flag]:
    flags = []
    for doc in room.documents:
        if doc.index is None:
            continue
        ahv, health = [], []
        for p, text in enumerate(doc.pages, 1):
            for m in _AHV.finditer(text):
                if _ahv_valid("756" + "".join(m.groups())):
                    ahv.append(_evidence(doc, p, m.start(), m.end()))
            for m in _HEALTH.finditer(text):
                around = text[max(0, m.start() - 160) : m.end() + 160]
                if _PERSON.search(around):
                    health.append(_evidence(doc, p, m.start(), m.end()))
        if not (ahv or health):
            continue
        found = []
        if ahv:
            found.append(f"{len(ahv)} AHV-Nummer{'n' if len(ahv) > 1 else ''} (Art. 153b ff. AHVG)")
        if health:
            found.append(f"Gesundheitsdaten zu einzelnen Personen (besonders schützenswert, Art. 5 lit. c DSG)")
        pages = sorted({e.page for e in ahv + health})
        flags.append(Flag(
            WARNUNG, "Datenschutz", f"Personendaten in {doc.label} {doc.title}",
            f"Gefunden: {' und '.join(found)}, auf S. {', '.join(map(str, pages))}. Für die Prüfung ist das selten "
            "nötig (Art. 6 Abs. 2 DSG). Vor der Weitergabe schwärzen oder in einen Clean Room mit beschränktem "
            "Zugang verschieben.", ahv + health, [doc.index]))
    return flags
