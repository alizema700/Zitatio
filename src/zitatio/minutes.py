"""Was steht in den Protokollen, das der Bericht nicht erwähnt?

Verwaltungsrats- und GV-Protokolle sind der Ort, an dem Probleme zuerst auftauchen: eine angekündigte
Steuerprüfung, ein Rückruf, ein Kunde, der kündigt. Zitatio sucht in allen Protokollen nach solchen
Themen und prüft, ob der Bericht das Thema irgendwo anspricht. Fehlt es im Bericht, ist das ein
Warnsignal; sonst ein Hinweis mit Fundstelle.
"""

from __future__ import annotations

import re

from .dataroom import DataRoom
from .swiss import HINWEIS, WARNUNG, Flag
from .verify import _evidence

TOPICS: list[tuple[str, re.Pattern]] = [
    (topic, re.compile(rx, re.IGNORECASE))
    for topic, rx in [
        ("Sanierung", r"sanierung|kapitalverlust|überschuldung|art\. 725|assainissement|perte de capital|surendettement"
                      r"|risanamento|perdita di capitale"),
        ("Rechtsstreit", r"rechtsstreit|\bklage\b|schiedsverfahren|prozessrisiko|litige|action en justice|arbitrage"
                         r"|contenzioso|arbitrato"),
        ("Behörden und Bussen", r"\bbusse\b|sanktion|strafverfahren|strafuntersuchung|untersuchung der|\bweko\b|\bfinma\b"
                                r"|amende|enquête|multa|inchiesta"),
        ("Steuerprüfung", r"steuerprüfung|nachsteuer|steuerverfahren|\bestv\b|steuerrevision|contrôle fiscal"
                          r"|rappel d'impôt|verifica fiscale"),
        ("Rückruf und Produkthaftung", r"rückruf|produkthaftung|swissmedic|rappel de produit|responsabilité du fait des produits"
                                       r"|richiamo"),
        ("Datenschutz und IT-Vorfälle", r"datenschutzverletzung|cyberangriff|hackerangriff|datenleck|ransomware"
                                        r"|violation de données|cyberattaque|violazione dei dati"),
        ("Abgänge in Organen", r"rücktritt|whistleblow|organhaftung|verantwortlichkeitsklage|démission|dimissioni"),
        ("Kundenverlust", r"kündigung durch|kündigt den|verlust des kunden|résiliation par|disdetta da parte"),
        ("Fortführung", r"going concern|fortführungsfähigkeit|unternehmensfortführung|continuité de l'exploitation"
                        r"|continuità aziendale"),
        ("Geschäfte mit Nahestehenden", r"darlehen an (?:den |die )?(?:aktionär|verwaltungsrat|organ)|nahestehende"
                                        r"|prêt (?:à l'actionnaire|aux administrateurs)|parti correlate"),
    ]
]
_MINUTES = re.compile(r"protokoll|procès-verba|verbale|minutes", re.IGNORECASE)
_SENTENCE = re.compile(r"(?:[^.!?]|[.!?](?=\d))+(?:[.!?]|$)")
# Formeln, die in jedem Vertrag stehen, sind kein Thema: "Streitigkeiten einvernehmlich beilegen"
_BOILERPLATE = re.compile(r"einvernehmlich|gerichtsstand|schriftform|unwirksam", re.IGNORECASE)


def check_minutes(room: DataRoom, report_text: str | None) -> list[Flag]:
    """report_text None: kein Bericht (Red-Flag-Bericht), jedes Thema ist ein Warnsignal ohne Bezug zum Bericht."""
    report_sentences = [m.group(0) for m in _SENTENCE.finditer((report_text or "").replace("\n", " "))]
    flags = []
    for doc in room.documents:
        if doc.index is None or not _MINUTES.search(doc.title):
            continue
        seen: set[tuple[str, str]] = set()
        for page_no, text in enumerate(doc.pages, 1):
            flat = text.replace("\n", " ")
            for m in _SENTENCE.finditer(flat):
                sentence = m.group(0).strip()
                if _BOILERPLATE.search(sentence):
                    continue
                for topic, rx in TOPICS:
                    hit = rx.search(sentence)
                    if not hit or (topic, sentence) in seen:
                        continue
                    seen.add((topic, sentence))
                    ev = _evidence(doc, page_no, m.start() + hit.start(), m.start() + hit.end())
                    mentioned = next((s for s in report_sentences if rx.search(s)), None)
                    where = f"{doc.label}, S. {page_no}"
                    if mentioned:
                        flags.append(Flag(HINWEIS, "Protokolle", f"{topic} ({where})",
                                          f"Im Protokoll: «{_trim(sentence)}» Der Bericht behandelt das Thema: "
                                          f"«{_trim(mentioned.strip())}»", [ev], [doc.index]))
                    elif report_text is None:
                        flags.append(Flag(WARNUNG, "Protokolle", f"{topic} ({where})", f"Im Protokoll: «{_trim(sentence)}»",
                                          [ev], [doc.index]))
                    else:
                        flags.append(Flag(WARNUNG, "Protokolle", f"{topic} ({where}), im Bericht nicht erwähnt",
                                          f"Im Protokoll: «{_trim(sentence)}» Der Bericht sagt nichts dazu.",
                                          [ev], [doc.index]))
    return flags


def _trim(text: str, width: int = 220) -> str:
    text = re.sub(r"\s+", " ", text)
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"
