"""Prüfkern: jede Aussage gegen ihre Fundstelle im Datenraum prüfen.

Grundsatz: Im Zweifel nie GEPRÜFT. Ein Status GEPRÜFT entsteht nur, wenn
jeder prüfbare Wert der Aussage auf der zitierten Seite steht oder ein
Prüfmodell die Aussage mit einem wörtlich nachweisbaren Zitat stützt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .dataroom import DataRoom, Document
from .facts import AMOUNT, DATE, DURATION, PERCENT, UID, Fact, extract_facts, uid_is_valid
from .report import Claim


class Status(Enum):
    GEPRUEFT = "geprueft"
    ABWEICHUNG = "abweichung"
    FALSCHE_FUNDSTELLE = "falsche_fundstelle"
    QUELLE_FEHLT = "quelle_fehlt"
    OHNE_BELEG = "ohne_beleg"
    UNGEPRUEFT = "ungeprueft"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]


STATUS_LABELS = {
    Status.GEPRUEFT: "Geprüft",
    Status.ABWEICHUNG: "Abweichung",
    Status.FALSCHE_FUNDSTELLE: "Falsche Fundstelle",
    Status.QUELLE_FEHLT: "Quelle fehlt",
    Status.OHNE_BELEG: "Ohne Beleg",
    Status.UNGEPRUEFT: "Ungeprüft",
}


@dataclass
class Evidence:
    doc_label: str
    doc_name: str
    page: int
    before: str
    match: str
    after: str


@dataclass
class Finding:
    claim: Claim
    status: Status
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    method: str = "Regeln"


@dataclass
class Verdict:
    """Antwort eines Prüfmodells. Wird nur verwendet, wenn `quote` wörtlich in der Quelle steht."""

    label: str  # GESTUETZT | WIDERSPRUCH | NICHT_BELEGT
    quote: str
    reason: str


ModelVerifier = Callable[[str, list[tuple[str, str]]], Verdict | None]


# --- Hilfsfunktionen --------------------------------------------------------

def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'")).strip()


def snippet(text: str, start: int, end: int, width: int = 110) -> tuple[str, str, str]:
    before = text[max(0, start - width) : start]
    after = text[end : end + width]
    before = ("…" if start > width else "") + _flat(before).lstrip()
    after = _flat(after).rstrip() + ("…" if end + width < len(text) else "")
    return before + (" " if text[start - 1 : start].isspace() else ""), _flat(text[start:end]), (
        (" " if text[end : end + 1].isspace() else "") + after
    )


def _evidence(doc: Document, page: int, start: int, end: int) -> Evidence:
    before, match, after = snippet(doc.pages[page - 1], start, end)
    return Evidence(doc.label, doc.name, page, before, match, after)


def _find(fact: Fact, doc: Document, pages: list[int]) -> tuple[int, Fact] | None:
    for page in pages:
        for candidate in extract_facts(doc.pages[page - 1]):
            if candidate.matches(fact):
                return page, candidate
    return None


def _nearest_values(fact: Fact, candidates: list[Fact]) -> list[str]:
    """Werte gleicher Art an der Fundstelle, die ähnlichsten zuerst."""

    def distance(c: Fact):
        a, b = fact.value, c.value
        if fact.kind == AMOUNT:
            return abs(a[1] - b[1]) if a[0] == b[0] else float("inf")
        if fact.kind == PERCENT:
            return abs(a - b)
        if fact.kind == DATE:
            return abs((a - b).days)
        if fact.kind == DURATION:
            return abs(a[0] - b[0]) if a[1] == b[1] else float("inf")
        return 0

    seen, out = set(), []
    for c in sorted(candidates, key=distance):
        if c.value not in seen:
            seen.add(c.value)
            out.append(c.display())
    return out


def quote_in_source(quote: str, source: str) -> int:
    """Position des Zitats in der Quelle (whitespace-tolerant), sonst -1."""
    q, s = _flat(quote).lower(), _flat(source).lower()
    if len(q) < 15:
        return -1
    return s.find(q)


_STOPWORDS = set("""aber alle als also auch auf aus bei bis das dass dem den der des die dies diese
dieser durch ein eine einem einen einer eines für hat haben ist mit nach nicht noch oder sich sie
sind über und vom von vor wird werden wurde zum zur zwischen gemäss gemäß sowie keine kein""".split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß]{4,}", text.lower()) if w not in _STOPWORDS}


def best_passage(claim_text: str, doc: Document, pages: list[int]) -> Evidence | None:
    """Ähnlichste Textstelle (Wortüberlappung) als Lesehilfe für die manuelle Prüfung."""
    wanted, best = _tokens(claim_text), None
    for page in pages:
        text = doc.pages[page - 1]
        for m in re.finditer(r"[^.!?]+(?:[.!?]|$)", text):
            score = len(wanted & _tokens(m.group(0)))
            if score and (best is None or score > best[0]):
                best = (score, page, m.start(), m.end())
    if best is None:
        return None
    _, page, start, end = best
    return _evidence(doc, page, start, end)


# --- Prüfung ----------------------------------------------------------------

def _resolve(claim: Claim, room: DataRoom):
    """Zitierte Seiten je Dokument und Fehler bei nicht auflösbaren Fundstellen."""
    resolved: list[tuple[Document, list[int]]] = []
    problems: list[str] = []
    for c in claim.citations:
        doc = room.get(c.index)
        if doc is None:
            problems.append(f"{c.label}: Dokument {c.index} gibt es im Datenraum nicht.")
            continue
        if c.page_from is None:
            pages = list(range(1, len(doc.pages) + 1))
        else:
            last = c.page_to or c.page_from
            if c.page_from < 1 or last > len(doc.pages):
                problems.append(
                    f"{c.label}: {doc.label} hat nur {len(doc.pages)} Seite(n)."
                )
                continue
            pages = list(range(c.page_from, last + 1))
        resolved.append((doc, pages))
    return resolved, problems


def _locate_elsewhere(fact: Fact, room: DataRoom, skip: set[tuple[str, int]]):
    for doc in room.documents:
        if doc.index is None:
            continue
        pages = [p for p in range(1, len(doc.pages) + 1) if (doc.name, p) not in skip]
        hit = _find(fact, doc, pages)
        if hit:
            return doc, hit
    return None


def verify_claim(claim: Claim, room: DataRoom, model: ModelVerifier | None = None) -> Finding:
    finding = Finding(claim, Status.UNGEPRUEFT)
    checkable = [f for f in claim.facts if f.kind != UID or uid_is_valid(f.value)]
    for f in claim.facts:
        if f.kind == UID and not uid_is_valid(f.value):
            finding.reasons.append(f"UID {f.value} ist ungültig (Prüfziffer stimmt nicht).")

    if not claim.citations:
        finding.status = Status.OHNE_BELEG
        finding.reasons.insert(0, "Keine Fundstelle angegeben.")
        hits = [_locate_elsewhere(f, room, set()) for f in checkable]
        if checkable and all(hits):
            places = sorted({f"{doc.label}, S. {page}" for doc, (page, _) in hits})
            finding.reasons.append(f"Beleg im Datenraum gefunden: {'; '.join(places)}.")
            for doc, (page, cand) in hits:
                finding.evidence.append(_evidence(doc, page, cand.start, cand.end))
        return finding

    resolved, problems = _resolve(claim, room)
    if problems:
        finding.status = Status.QUELLE_FEHLT
        finding.reasons = problems + finding.reasons
        return finding

    cited = {(doc.name, p) for doc, pages in resolved for p in pages}
    missing: list[Fact] = []
    for fact in checkable:
        hit = next(((doc, h) for doc, pages in resolved if (h := _find(fact, doc, pages))), None)
        if hit:
            doc, (page, cand) = hit
            finding.evidence.append(_evidence(doc, page, cand.start, cand.end))
        else:
            missing.append(fact)

    if finding.reasons:  # ungültige UID
        finding.status = Status.ABWEICHUNG
    elif checkable and not missing:
        finding.status = Status.GEPRUEFT
        finding.reasons.append(
            "Alle Werte (" + ", ".join(f.display() for f in checkable) + ") stehen an der Fundstelle."
        )
    elif missing:
        elsewhere = [_locate_elsewhere(f, room, cited) for f in missing]
        if all(elsewhere):
            finding.status = Status.FALSCHE_FUNDSTELLE
            for fact, (doc, (page, cand)) in zip(missing, elsewhere):
                finding.reasons.append(
                    f"{fact.display()} steht nicht an der Fundstelle, sondern in {doc.label}, S. {page}."
                )
                finding.evidence.append(_evidence(doc, page, cand.start, cand.end))
        else:
            finding.status = Status.ABWEICHUNG
            for fact in missing:
                others = _nearest_values(fact, [
                    c
                    for doc, pages in resolved
                    for p in pages
                    for c in extract_facts(doc.pages[p - 1])
                    if c.kind == fact.kind
                ])
                note = f" Die Fundstelle nennt: {', '.join(others[:3])}." if others else ""
                finding.reasons.append(f"{fact.display()} steht nicht an der Fundstelle.{note}")
    else:
        finding.reasons.append(
            "Fundstelle vorhanden, aber die Aussage enthält keine automatisch prüfbaren Werte. "
            "Bitte manuell prüfen."
        )
        for doc, pages in resolved:
            passage = best_passage(claim.clean_text, doc, pages)
            if passage:
                finding.evidence.append(passage)

    if model and finding.status in (Status.GEPRUEFT, Status.UNGEPRUEFT):
        _apply_model(finding, resolved, model)
    return finding


def _apply_model(finding: Finding, resolved, model: ModelVerifier) -> None:
    passages = [(f"{doc.label}, S. {p}", doc.pages[p - 1]) for doc, pages in resolved for p in pages]
    try:
        verdict = model(finding.claim.clean_text, passages)
    except Exception as exc:  # Modell nicht erreichbar: Regelergebnis bleibt
        finding.reasons.append(f"Prüfmodell nicht verfügbar ({exc.__class__.__name__}).")
        return
    if verdict is None:
        return
    for doc, pages in resolved:
        for p in pages:
            pos = quote_in_source(verdict.quote, doc.pages[p - 1])
            if pos >= 0:
                break
        else:
            continue
        break
    else:
        finding.reasons.append("Antwort des Prüfmodells verworfen: Zitat steht nicht in der Quelle.")
        return

    flat = _flat(doc.pages[p - 1])
    quote_len = len(_flat(verdict.quote))
    evidence = Evidence(doc.label, doc.name, p, *snippet(flat, pos, pos + quote_len))
    finding.method = "Regeln + Modell" if finding.claim.facts else "Modell"
    if verdict.label == "GESTUETZT":
        finding.status = Status.GEPRUEFT
        finding.reasons.append(f"Prüfmodell: gestützt. {verdict.reason}".strip())
    else:
        finding.status = Status.ABWEICHUNG
        word = "Widerspruch" if verdict.label == "WIDERSPRUCH" else "nicht gestützt"
        finding.reasons.append(f"Prüfmodell: {word}. {verdict.reason}".strip())
    finding.evidence.insert(0, evidence)


def verify(claims: list[Claim], room: DataRoom, model: ModelVerifier | None = None) -> list[Finding]:
    return [verify_claim(c, room, model) for c in claims]
