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
from .facts import AMOUNT, DATE, DURATION, PERCENT, UID, Fact, page_facts, uid_is_valid
from .report import Claim, quotes
from .tables import LABELS, Cell, cell_at, doc_cells, metrics_in, years_in


class Status(Enum):
    GEPRUEFT = "geprueft"
    ABWEICHUNG = "abweichung"
    WIDERSPRUCH = "widerspruch"
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
    Status.WIDERSPRUCH: "Widerspruch",
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
    # Wo die Werte der Aussage stehen: (Dateiname, Seite, Position) für die Querprüfung
    hits: list[tuple[str, int, int]] = field(default_factory=list)
    # Werte, die nirgends an der Fundstelle stehen (Kandidaten zum Nachrechnen)
    missing: list[Fact] = field(default_factory=list)


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


@dataclass
class _Context:
    """Was die Aussage über einen Wert sagt: Grösse (EBITDA, Umsatz …) und Jahr."""

    metric: str | None
    metrics: set[str]
    year: int | None


def _context(claim: Claim, fact: Fact) -> _Context:
    text = claim.clean_text
    found = metrics_in(text)
    metric = None
    after = [m for m in found if 0 <= m[1] - fact.end <= 4]  # "CHF 2.3 Mio. EBITDA"
    before = [m for m in found if m[2] <= fact.start]
    if after:
        metric = after[0][0]
    elif before:
        metric = before[-1][0]
    elif found:
        metric = found[0][0]
    years = years_in(text)
    return _Context(metric, {m[0] for m in found}, years[0] if len(years) == 1 else None)


def _misfit(ctx: _Context | None, cell: Cell | None) -> str | None:
    """Warum ein gefundener Wert nicht zur Aussage passt: 'jahr', 'groesse' oder None."""
    if ctx is None or cell is None or cell.metric is None or not cell.tabular:
        return None
    if ctx.metric and cell.metric != ctx.metric and cell.metric not in ctx.metrics:
        return "groesse"
    if ctx.year and cell.year and cell.year != ctx.year and (cell.metric == ctx.metric or not ctx.metric):
        return "jahr"
    return None


@dataclass
class _Hit:
    doc: Document
    page: int
    fact: Fact  # der Wert auf der Seite
    cell: Cell | None
    misfit: str | None


def _find(fact: Fact, doc: Document, pages: list[int], ctx: _Context | None = None) -> _Hit | None:
    """Fundort eines Werts: passende Zeile und Spalte vor unpassender, exakt vor gerundet."""
    best, best_rank = None, None
    for page in pages:
        cells = doc_cells(doc, page) if fact.kind == AMOUNT else ()
        for candidate in page_facts(doc.pages[page - 1]):
            how = fact.match(candidate)
            if not how:
                continue
            cell = cell_at(cells, candidate)
            misfit = _misfit(ctx, cell)
            rank = (misfit is not None, how != "exakt")
            if best_rank is None or rank < best_rank:
                best, best_rank = _Hit(doc, page, candidate, cell, misfit), rank
                if rank == (False, False):
                    return best
    return best


def _find_in(fact: Fact, resolved, ctx: _Context | None) -> _Hit | None:
    hits = [h for doc, pages in resolved if (h := _find(fact, doc, pages, ctx))]
    return min(hits, key=lambda h: (h.misfit is not None, fact.match(h.fact) != "exakt"), default=None)


def _expected_cell(hit: _Hit, ctx: _Context) -> Cell | None:
    """Der Wert, den die Aussage gemeint haben müsste: gleiche Zeile im richtigen Jahr,
    oder die genannte Grösse in derselben Spalte."""
    for c in doc_cells(hit.doc, hit.page):
        if not c.tabular:
            continue
        if hit.misfit == "jahr" and c.line == hit.cell.line and c.year == ctx.year:
            return c
        if hit.misfit == "groesse" and c.metric == ctx.metric and c.year == hit.cell.year:
            return c
    return None


def _misfit_reason(fact: Fact, hit: _Hit, ctx: _Context) -> tuple[str, Cell | None]:
    expected = _expected_cell(hit, ctx)
    if hit.misfit == "jahr":
        text = f"{fact.display()} steht an der Fundstelle in der Spalte {hit.cell.year}, die Aussage betrifft {ctx.year}."
        if expected:
            text += f" Für {ctx.year} nennt die Fundstelle {expected.fact.display()}."
    else:
        text = (f"{fact.display()} ist an der Fundstelle der Wert für «{hit.cell.label}», "
                f"nicht für {LABELS[ctx.metric]}.")
        if expected:
            text += f" {LABELS[ctx.metric][0].upper() + LABELS[ctx.metric][1:]} laut Fundstelle: {expected.fact.display()}."
    return text, expected


def _wanted_cell(fact: Fact, ctx: _Context, resolved) -> tuple[Document, int, Cell] | None:
    """Für eine Abweichung: der Tabellenwert der genannten Grösse im genannten Jahr."""
    if fact.kind != AMOUNT or not ctx.metric:
        return None
    for doc, pages in resolved:
        for p in pages:
            for c in doc_cells(doc, p):
                if c.tabular and c.metric == ctx.metric and (ctx.year is None or c.year == ctx.year):
                    if c.period and not c.period[0].isdigit() and c.period != str(ctx.year):
                        continue  # Monatswert, wenn die Aussage ein Jahr meint
                    return doc, p, c
    return None


def _how(fact: Fact, found: Fact) -> str:
    """Kurzer Zusatz, wenn der Wert nicht wörtlich gleich an der Fundstelle steht."""
    notes = []
    if found.unit:
        notes.append(f"Tabelle: {found.text} {found.unit}")
    elif fact.value != found.value:
        notes.append(f"Quelle: {found.display()}")
    if fact.value != found.value:
        notes.append("gerundet")
    return f"{fact.display()} ({', '.join(notes)})" if notes else fact.display()


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


def quote_text(text: str) -> str:
    """Text ohne Anführungszeichen und mit einfachen Leerzeichen; Zitatpositionen beziehen sich darauf."""
    return _flat(re.sub(r"[„“”«»\"]", "", text).replace("–", "-"))


def _quote_norm(text: str) -> str:
    return quote_text(text).lower()


def quote_in_source(quote: str, source: str) -> int:
    """Position des Zitats in der Quelle (whitespace- und anführungszeichen-tolerant), sonst -1.

    Auslassungen ("…", "[...]") sind erlaubt: Jeder Teil muss in dieser Reihenfolge vorkommen.
    """
    parts = [_quote_norm(p) for p in re.split(r"\s*(?:\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.)\s*", quote)]
    parts = [p.strip(" .,;:") for p in parts if p.strip(" .,;:")]
    s = _quote_norm(source)
    if not parts or any(len(p) < 15 for p in parts):
        return -1
    first = pos = s.find(parts[0])
    for p in parts[1:]:
        if pos < 0:
            break
        pos = s.find(p, pos + 1)
    return first if pos >= 0 else -1


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


def _locate_elsewhere(fact: Fact, room: DataRoom, skip: set[tuple[str, int]], ctx: _Context | None = None):
    fallback = None
    for doc in room.documents:
        if doc.index is None:
            continue
        pages = [p for p in range(1, len(doc.pages) + 1) if (doc.name, p) not in skip]
        hit = _find(fact, doc, pages, ctx)
        if hit and hit.misfit is None:
            return hit
        fallback = fallback or hit
    return None if ctx else fallback


def _locate_quote(quote: str, room: DataRoom, skip: set[tuple[str, int]]):
    for doc in room.documents:
        if doc.index is None:
            continue
        for p in range(1, len(doc.pages) + 1):
            if (doc.name, p) not in skip and quote_in_source(quote, doc.pages[p - 1]) >= 0:
                return doc, p
    return None


def _quote_evidence(quote: str, doc: Document, page: int) -> Evidence:
    flat = quote_text(doc.pages[page - 1])
    pos = quote_in_source(quote, flat)
    return Evidence(doc.label, doc.name, page, *snippet(flat, pos, pos + len(quote_text(quote))))


# --- Dokumentbezug: nennt die Aussage ein anderes Dokument als das zitierte? -----

_DOC_NOUN_RE = re.compile(
    r"\b[A-ZÄÖÜ][a-zäöüß]+(?:vertrag|vertrages|verträge|rechnung|auszug|plan|erklärung|verfügung|police|policen"
    r"|reglement|protokoll|protokolle|statuten|bericht|liste|abrechnung|abrechnungen|lizenz|klage)\b"
)
_COMPANY_RE = re.compile(
    r"\b((?:[A-ZÄÖÜ][\w&'’.-]*\s+){1,4}(?:AG|GmbH|SA|Sàrl|KG|SE|Ltd\.?|Inc\.?))(?!\w)"
)


def _norm_ref(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("verträg", "vertrag"))


def _stem(word: str) -> str:
    w = _norm_ref(word)
    for suffix in ("es", "en", "e", "n", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 6:
            return w[: -len(suffix)]
    return w


def _doc_reference_problems(claim: Claim, resolved, room: DataRoom) -> list[tuple[str, Document]]:
    """Begriffe der Aussage (Dokumentart, Firma), die nur zu einem anderen Dokument passen."""
    cited = [doc for doc, _ in resolved]
    problems = []
    for m in _DOC_NOUN_RE.finditer(claim.clean_text):
        stem = _stem(m.group(0))
        if any(stem in _norm_ref(" ".join([d.title, d.pages[0] if d.pages else ""] + [d.pages[p - 1] for p in pages]))
               for d, pages in resolved):
            continue
        other = next((d for d in room.documents if d.index and d not in cited and stem in _norm_ref(d.title)), None)
        if other:
            problems.append((m.group(0), other))
    for m in _COMPANY_RE.finditer(claim.clean_text):
        words = m.group(1).split()
        names = [" ".join(words[i:]) for i in range(len(words) - 1)]  # "Gemäss Lakeside Dental SA" -> "Lakeside Dental SA"
        if any(_norm_ref(n) in _norm_ref(d.title + " " + " ".join(d.pages)) for d in cited for n in names):
            continue
        other = next((d for n in names for d in room.documents
                      if d.index and d not in cited and _norm_ref(n) in _norm_ref(d.title)), None)
        if other:
            problems.append((next(n for n in names if _norm_ref(n) in _norm_ref(other.title)), other))
    return problems


def verify_claim(claim: Claim, room: DataRoom, model: ModelVerifier | None = None) -> Finding:
    finding = Finding(claim, Status.UNGEPRUEFT)
    checkable = [f for f in claim.facts if f.kind != UID or uid_is_valid(f.value)]
    for f in claim.facts:
        if f.kind == UID and not uid_is_valid(f.value):
            finding.reasons.append(f"UID {f.value} ist ungültig (Prüfziffer stimmt nicht).")

    if not claim.citations:
        finding.status = Status.OHNE_BELEG
        finding.reasons.insert(0, "Keine Fundstelle angegeben.")
        hits = [_locate_elsewhere(f, room, set(), _context(claim, f)) for f in checkable]
        quote_places = [_locate_quote(q, room, set()) for q in quotes(claim.clean_text)]
        if (checkable or quote_places) and all(hits) and all(quote_places):
            places = sorted({f"{h.doc.label}, S. {h.page}" for h in hits} | {f"{d.label}, S. {p}" for d, p in quote_places})
            finding.reasons.append(f"Beleg im Datenraum gefunden: {'; '.join(places)}.")
            for h in hits:
                finding.evidence.append(_evidence(h.doc, h.page, h.fact.start, h.fact.end))
                finding.hits.append((h.doc.name, h.page, h.fact.start))
            for d, p in quote_places:
                finding.evidence.append(_quote_evidence(quotes(claim.clean_text)[0], d, p))
        else:
            finding.missing = [f for f, h in zip(checkable, hits) if not h]
        return finding

    resolved, problems = _resolve(claim, room)
    if problems:
        finding.status = Status.QUELLE_FEHLT
        finding.reasons = problems + finding.reasons
        return finding

    cited = {(doc.name, p) for doc, pages in resolved for p in pages}
    missing: list[Fact] = []
    misfits: list[str] = []
    found: list[str] = []
    for fact in checkable:
        ctx = _context(claim, fact)
        hit = _find_in(fact, resolved, ctx)
        if hit and hit.misfit is None:
            finding.evidence.append(_evidence(hit.doc, hit.page, hit.fact.start, hit.fact.end))
            finding.hits.append((hit.doc.name, hit.page, hit.fact.start))
            found.append(_how(fact, hit.fact))
        elif hit:
            text, expected = _misfit_reason(fact, hit, ctx)
            misfits.append(text)
            finding.evidence.append(_evidence(hit.doc, hit.page, hit.fact.start, hit.fact.end))
            if expected:
                finding.evidence.append(_evidence(hit.doc, hit.page, expected.fact.start, expected.fact.end))
        else:
            missing.append(fact)

    # Wörtliche Zitate müssen wörtlich an der Fundstelle stehen.
    wrong_quotes: list[str] = []
    for quote in quotes(claim.clean_text):
        place = next(((doc, p) for doc, pages in resolved for p in pages if quote_in_source(quote, doc.pages[p - 1]) >= 0), None)
        if place:
            finding.evidence.append(_quote_evidence(quote, *place))
            found.append(f"Zitat «{_short(quote)}»")
        else:
            wrong_quotes.append(quote)

    if finding.reasons:  # ungültige UID
        finding.status = Status.ABWEICHUNG
    elif misfits:
        finding.status = Status.ABWEICHUNG
        finding.reasons.extend(misfits)
        for fact in missing:
            finding.reasons.append(f"{fact.display()} steht nicht an der Fundstelle.")
        _quote_reasons(finding, wrong_quotes, room, cited, resolved)
    elif (checkable or quotes(claim.clean_text)) and not missing and not wrong_quotes:
        finding.status = Status.GEPRUEFT
        if checkable:
            finding.reasons.append("Alle Werte (" + ", ".join(found) + ") stehen an der Fundstelle.")
        else:
            finding.reasons.append(f"Das Zitat «{_short(quotes(claim.clean_text)[0])}» steht wörtlich an der Fundstelle.")
    elif missing or wrong_quotes:
        elsewhere = [_locate_elsewhere(f, room, cited, _context(claim, f)) for f in missing]
        quote_places = [_locate_quote(q, room, cited) for q in wrong_quotes]
        if all(elsewhere) and all(quote_places):
            finding.status = Status.FALSCHE_FUNDSTELLE
            for fact, hit in zip(missing, elsewhere):
                finding.reasons.append(
                    f"{fact.display()} steht nicht an der Fundstelle, sondern in {hit.doc.label}, S. {hit.page}."
                )
                finding.evidence.append(_evidence(hit.doc, hit.page, hit.fact.start, hit.fact.end))
            for quote, (doc, p) in zip(wrong_quotes, quote_places):
                finding.reasons.append(f"Das Zitat «{_short(quote)}» steht nicht an der Fundstelle, sondern in {doc.label}, S. {p}.")
                finding.evidence.append(_quote_evidence(quote, doc, p))
        else:
            finding.status = Status.ABWEICHUNG
            finding.missing = missing
            for fact in missing:
                ctx = _context(claim, fact)
                wanted = _wanted_cell(fact, ctx, resolved)
                if wanted:
                    doc, p, cell = wanted
                    when = f" {cell.period}" if cell.period else ""
                    label = LABELS[cell.metric]
                    finding.reasons.append(
                        f"{fact.display()} steht nicht an der Fundstelle. Für {label}{when} nennt die Fundstelle "
                        f"{cell.fact.display()}."
                    )
                    finding.evidence.append(_evidence(doc, p, cell.fact.start, cell.fact.end))
                    continue
                others = _nearest_values(fact, [
                    c
                    for doc, pages in resolved
                    for p in pages
                    for c in page_facts(doc.pages[p - 1])
                    if c.kind == fact.kind
                ])
                note = f" Die Fundstelle nennt: {', '.join(others[:3])}." if others else ""
                finding.reasons.append(f"{fact.display()} steht nicht an der Fundstelle.{note}")
            _quote_reasons(finding, wrong_quotes, room, cited, resolved)
    else:
        finding.reasons.append(
            "Fundstelle vorhanden, aber die Aussage enthält keine automatisch prüfbaren Werte. "
            "Bitte manuell prüfen."
        )
        for doc, pages in resolved:
            passage = best_passage(claim.clean_text, doc, pages)
            if passage:
                finding.evidence.append(passage)

    # Nennt die Aussage einen Vertrag oder eine Firma, die zu einem anderen Dokument gehört?
    for word, other in _doc_reference_problems(claim, resolved, room):
        cited_labels = ", ".join(sorted({doc.label for doc, _ in resolved}))
        finding.reasons.insert(0, f"Die Aussage nennt «{word}», {cited_labels} handelt nicht davon. "
                                  f"Passend wäre {other.label} {other.title}.")
        if finding.status in (Status.GEPRUEFT, Status.UNGEPRUEFT):
            finding.status = Status.FALSCHE_FUNDSTELLE
            finding.method = "Regeln"

    if model and finding.status in (Status.GEPRUEFT, Status.UNGEPRUEFT):
        _apply_model(finding, resolved, model)
    return finding


def _short(quote: str, width: int = 70) -> str:
    quote = _flat(quote)
    return quote if len(quote) <= width else quote[: width - 1].rstrip() + "…"


def _quote_reasons(finding: Finding, wrong_quotes: list[str], room: DataRoom, cited, resolved) -> None:
    for quote in wrong_quotes:
        place = _locate_quote(quote, room, cited)
        if place:
            finding.reasons.append(f"Das Zitat «{_short(quote)}» steht nicht an der Fundstelle, sondern in "
                                   f"{place[0].label}, S. {place[1]}.")
            finding.evidence.append(_quote_evidence(quote, *place))
            continue
        finding.reasons.append(f"Das Zitat «{_short(quote)}» steht so nicht im Datenraum (verändert oder erfunden).")
        for doc, pages in resolved:
            passage = best_passage(quote, doc, pages)
            if passage:
                finding.evidence.append(passage)
                break


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

    flat = quote_text(doc.pages[p - 1])
    quote_len = len(quote_text(verdict.quote))
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
