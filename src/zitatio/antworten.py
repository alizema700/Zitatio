"""Antwortentwürfe für die Q&A-Liste, mit Fundstelle.

Im Verkaufsprozess beantwortet die Verkäuferseite hunderte Fragen der Käufer. Die meisten Antworten stehen schon
im Datenraum. Zitatio sucht pro Frage die passenden Seiten (BM25, wie die Belegsuche) und darauf den Satz, der die
Frage am besten trifft, und nennt Dokument und Seite. Ein Entwurf: Wer ihn freigibt, liest die Fundstelle. Findet
Zitatio nichts Tragfähiges, sagt es das, statt etwas zu erfinden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dataroom import DataRoom
from .facts import AMOUNT, DATE, DURATION, PERCENT, extract_facts
from .locate import _FOLD, _terms, page_index

_SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?=\d))+(?:[.!?]|$)", re.MULTILINE)
_WANTS_VALUE = re.compile(r"\b(?:wie (?:hoch|viel\w*|lange|gross)|wann|bis wann|welche[rs]? (?:betrag|summe|datum)"
                          r"|how (?:much|many|long)|when|combien|quand|quanto|quando)\b", re.IGNORECASE)


@dataclass
class Answer:
    number: int
    question: str
    text: str  # Satz aus dem Datenraum, oder leer
    reference: str  # "DR 2.3, S. 4"
    score: float
    warning: str = ""  # der Datenraum nennt zu diesem Wert verschiedene Zahlen


def read_questions(data: bytes, suffix: str) -> list[str]:
    """Fragen aus Text, Markdown oder Excel (Spalte "Frage", sonst die erste Textspalte)."""
    if suffix in (".xlsx", ".xlsm"):
        from .xlsx import xlsx_to_pages

        rows = [line.split("; ") for page in xlsx_to_pages(data) for line in page.splitlines()
                if not line.startswith("Blatt:")]
        if not rows:
            return []
        head = [c.strip().lower() for c in rows[0]]
        col = next((i for i, h in enumerate(head) if h in ("frage", "question", "fragen", "questions")), None)
        body = rows[1:] if col is not None else rows
        col = col if col is not None else max(range(len(rows[0])), key=lambda i: len(rows[0][i]))
        return [r[col].strip() for r in body if len(r) > col and len(r[col].split()) >= 3]
    out = []
    for line in data.decode("utf-8-sig", errors="replace").splitlines():
        if line.strip().startswith("|"):  # Markdown-Tabelle: die Zelle mit der Frage
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            line = next((c for c in cells if c.endswith("?")), max(cells, key=len))
            if set(line) <= set("-: "):
                continue
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if line.endswith("?") or (len(line.split()) >= 3 and not line.startswith("#")):
            out.append(line)
    return out


_QUESTION_WORDS = {"wie", "hoch", "wann", "gibt", "wer", "hat", "haben", "welche", "welcher", "welches", "was", "wo",
                   "viel", "viele", "lange", "war", "waren", "bestehen", "besteht", "läuft", "ist", "sind", "es", "ab",
                   "eine", "einen", "der", "die", "das", "des", "dem", "den", "für", "mit", "von", "im", "in", "zum",
                   "zur", "bei", "gesellschaft", "how", "when", "what", "which", "does", "the", "there", "any", "is",
                   "quel", "quelle", "quand", "combien", "est", "les", "des"}
# Wörter, die in Fragen und Unterlagen verschieden heissen
_SYNONYMS = {
    "umsatz": ("nettoerlös", "erlös", "umsatzerlös"), "gehalt": ("lohn", "salär", "vergütung"),
    "lohn": ("gehalt", "salär", "vergütung"), "rechtsstreit": ("klage", "verfahren", "prozess"),
    "rechtsstreitigkeiten": ("klage", "verfahren", "prozess"), "klage": ("verfahren", "streitwert"),
    "endet": ("bis", "ablauf"), "ende": ("bis", "ablauf"), "ceo": ("vorsitzender",),
    "pensionskasse": ("vorsorgeeinrichtung", "vorsorge"), "zertifikat": ("zertifizierung",),
    "streitwert": ("schadenersatz", "fordert", "forderung"), "kündigungsfrist": ("frist", "kündigen"),
    "schulden": ("verbindlichkeiten", "kredit"), "mitarbeitende": ("vollzeitstellen", "fte", "personal"),
}


def _words(text: str) -> list[str]:
    return [w.translate(_FOLD) for w in re.findall(r"[a-zäöüàâéèêëîïôûùç]{2,}", text.lower())]


def _question_terms(q: str) -> list[tuple[str, ...]]:
    """Pro Begriff der Frage die Formen, die im Datenraum dafür stehen können."""
    out = []
    for w in re.findall(r"[a-zäöüàâéèêëîïôûùç]{3,}", q.lower()):
        if w in _QUESTION_WORDS:
            continue
        out.append(tuple(x.translate(_FOLD) for x in (w, *_SYNONYMS.get(w, ()))))
    return out


def _matches(forms: tuple[str, ...], words: list[str]) -> bool:
    # "gehalt" trifft "bruttojahresgehalt", "rechtsstreit" trifft "rechtsstreitigkeiten"; kurze Formen nur ganz
    # "zeichnungsberechtigt" trifft "zeichnungsberechtigung", "kontrollwechselklausel" trifft "kontrollwechsel"
    return any((f[: max(5, len(f) - 3)] in w or (len(w) >= 8 and w in f)) if len(f) >= 5 else f == w
               for f in forms for w in words)


_KIND_WANTED = [(re.compile(r"\bwann\b|bis wann|endet|läuft .*ab|ablauf|\bwhen\b|quand|quando", re.I), DATE),
                (re.compile(r"wie (?:hoch|viel)|betrag|how much|combien|quanto", re.I), AMOUNT),
                (re.compile(r"wie lange|frist|how long", re.I), DURATION)]


def answer(questions: list[str], room: DataRoom) -> list[Answer]:
    from .crosscheck import find_conflicts

    index = page_index(room)
    conflicts = {s.where: c for c in find_conflicts(room) for s in c.sightings}
    out = []
    for n, q in enumerate(questions, 1):
        terms = _question_terms(q)
        idf = [index.idf.get(_terms(t[0])[0] if _terms(t[0]) else t[0], 2.0) for t in terms]
        weight = sum(idf) or 1
        wants_value = bool(_WANTS_VALUE.search(q))
        query = " ".join(f for t in terms for f in t)
        kinds = {k for rx, k in _KIND_WANTED if rx.search(q)}
        years = set(re.findall(r"\b20\d\d\b", q))
        best = None
        for rank, (doc, page, _) in enumerate(index.search(query, k=15)):
            title = _words(doc.title)
            previous: list[str] = []
            for m in _SENTENCE.finditer(doc.pages[page - 1]):
                sentence = re.sub(r"\s+", " ", m.group(0)).strip(" ;|")
                words = _words(sentence)
                before, previous = previous, words
                if len(sentence.split()) < 4 or sentence.endswith("?") or sentence.startswith(doc.title):
                    continue
                hit = [i for i, t in enumerate(terms) if _matches(t, words)]
                # Titel und vorheriger Satz zählen halb: "Mietvertrag Büro Zürich" / die Frage in der Q&A-Zeile
                ctx = [i for i, t in enumerate(terms) if i not in hit and _matches(t, title + before)]
                cover = (sum(idf[i] for i in hit) + 0.5 * sum(idf[i] for i in ctx)) / weight
                if not hit or cover < 0.55:
                    continue
                facts = extract_facts(sentence)
                if wants_value and not facts and not re.search(r"\d[\d'’]{3,}", sentence):
                    continue
                # Kürzere Sätze antworten direkter; lange tragen oft eine Ausnahme (Kontrollwechsel, Vorbehalt)
                score = cover - rank * 0.005 - 0.01 * max(0, len(words) - 14)
                if kinds & {f.kind for f in facts} or (AMOUNT in kinds and any(f.kind == PERCENT for f in facts)):
                    score += 0.2
                if years and (years & set(re.findall(r"\b20\d\d\b", sentence + " " + doc.title))):
                    score += 0.2
                if best is None or score > best[0]:
                    best = (score, sentence, f"{doc.label}, S. {page}")
        if best:
            c = conflicts.get(best[2])
            # Nur warnen, wenn der Satz den Wert aus dem Widerspruch nennt
            hit = c and any(s.where == best[2] and " ".join(s.evidence.match.split()) in best[1] for s in c.sightings)
            warning = f"Widerspruch im Datenraum: {c.describe()}" if hit else ""
            out.append(Answer(n, q, best[1], best[2], round(best[0], 2), warning))
        else:
            out.append(Answer(n, q, "", "", 0.0))
    return out


def to_markdown(answers: list[Answer]) -> str:
    cell = lambda t: t.replace("|", "/")  # noqa: E731
    lines = ["# Antwortentwürfe aus dem Datenraum", "",
             "_Entwurf von Zitatio: jede Antwort ist ein Satz aus dem Datenraum mit Fundstelle. Vor der Freigabe lesen._",
             "", "| Nr | Frage | Antwortentwurf | Fundstelle |", "|---|---|---|---|"]
    for a in answers:
        text = a.text or "Im Datenraum nicht gefunden. Antwort beim Management einholen."
        if a.warning:
            text += f" **Achtung:** {a.warning}"
        lines.append(f"| {a.number} | {cell(a.question)} | {cell(text)} | {a.reference or '–'} |")
    return "\n".join(lines) + "\n"
