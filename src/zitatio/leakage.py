"""Leakage nach dem Locked-Box-Stichtag.

Bei einem Locked-Box-Preis kauft der Käufer die Gesellschaft auf Basis einer Bilanz zu einem Stichtag. Fliesst
danach Geld an den Verkäufer oder ihm nahestehende Personen (Dividenden, Management Fees, Darlehen,
Boni für den Verkauf), sinkt der Wert, ohne dass der Preis sich ändert. Zitatio liest den Stichtag aus dem
SPA-Entwurf oder dem Bericht und sucht im Datenraum nach solchen Zahlungen mit Datum nach dem Stichtag.
"""

from __future__ import annotations

import datetime as dt
import re

from .dataroom import DataRoom
from .facts import AMOUNT, DATE, extract_facts
from .swiss import WARNUNG, Flag
from .verify import _evidence

_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")
_LOCKED_BOX = re.compile(r"locked[- ]?box|comptes de référence|bilancio di riferimento", re.IGNORECASE)
_KINDS = [
    ("Dividende", r"dividende|ausschüttung|dividend|distribution|dividendo"),
    ("Management Fee", r"management[- ]fee|verwaltungsgebühr|konzernumlage|frais de gestion"),
    ("Darlehen an Nahestehende", r"darlehen an (?:die |den )?(?:aktionär|verkäufer|verwaltungsr|holding|gesellschafter)"
                                 r"|prêt (?:à l'actionnaire|au vendeur)"),
    ("Bonus für den Verkauf", r"(?:transaktions|verkaufs|exit|deal)[- ]?bonus|retention[- ]bonus|prime de transaction"),
    ("Zahlung an Nahestehende", r"(?:bezahlt|überwiesen|vergütet)\w*[^.]{0,60}an (?:die |den )?(?:aktionär|verkäufer|holding)"
                                r"|an (?:die |den )?(?:aktionär|verkäufer|\w+ holding)\w*[^.]{0,60}(?:bezahlt|überwiesen)"),
    ("Forderungsverzicht", r"forderungsverzicht|verzicht\w* auf (?:die |eine )?forderung|renonciation à la créance"),
]
_KIND_RX = [(k, re.compile(rx, re.IGNORECASE)) for k, rx in _KINDS]


def locked_box_date(*texts: str) -> dt.date | None:
    for text in texts:
        if not text:
            continue
        for m in _SENTENCE.finditer(text.replace("\n", " ")):
            sentence = m.group(0)
            if _LOCKED_BOX.search(sentence):
                dates = [f.value for f in extract_facts(sentence) if f.kind == DATE]
                if dates:
                    return dates[0]
    return None


def check_leakage(room: DataRoom, box_date: dt.date | None) -> list[Flag]:
    if box_date is None:
        return []
    flags = []
    for doc in room.documents:
        if doc.index is None:
            continue
        for page_no, text in enumerate(doc.pages, 1):
            flat = text.replace("\n", " ")
            for m in _SENTENCE.finditer(flat):
                sentence = m.group(0)
                kind, hit = next(((k, rx.search(sentence)) for k, rx in _KIND_RX if rx.search(sentence)), (None, None))
                if kind is None:
                    continue
                facts = extract_facts(sentence)
                dates = [f.value for f in facts if f.kind == DATE and f.value > box_date]
                if not dates:
                    continue
                amounts = [f for f in facts if f.kind == AMOUNT]
                amount = f" über {amounts[0].display()}" if amounts else ""
                flags.append(Flag(
                    WARNUNG, "Leakage", f"{kind}{amount} nach dem Locked-Box-Stichtag ({doc.label}, S. {page_no})",
                    f"«{_trim(sentence)}» Der Stichtag ist der {box_date:%d.%m.%Y}. Im SPA als erlaubte Leakage "
                    "aufführen oder vom Verkäufer franken-genau zurückverlangen.",
                    [_evidence(doc, page_no, m.start() + hit.start(), m.start() + hit.end())], [doc.index]))
    return flags


def _trim(text: str, width: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"
