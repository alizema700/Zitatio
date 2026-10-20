"""DD-Bericht in einzelne Aussagen mit Fundstellen zerlegen."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .dataroom import read_pages
from .facts import MONTHS, Fact, extract_facts


@dataclass(frozen=True)
class Citation:
    index: str
    page_from: int | None
    page_to: int | None
    raw: str

    @property
    def label(self) -> str:
        if self.index.startswith("Q&A"):
            return self.index
        if self.page_from is None:
            return f"DR {self.index}"
        if self.page_to and self.page_to != self.page_from:
            return f"DR {self.index}, S. {self.page_from}–{self.page_to}"
        return f"DR {self.index}, S. {self.page_from}"


@dataclass
class Claim:
    number: int
    text: str  # Satz inkl. Fundstellen
    clean_text: str  # Satz ohne Fundstellen
    section: str
    citations: list[Citation] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    before: str = ""  # vorhergehender Satz im selben Abschnitt, für die Belegsuche ohne Fundstelle


# "[DR 3.2.1, S. 4]", "(VDR 2.1 p. 3-4)", "[Datenraum 5.3; DR 1.1, Seite 2]"
_BRACKET_RE = re.compile(r"[\[(]\s*((?:DR|VDR|Datenraum|Data\s*Room|Q\s*&\s*A(?![\w&]))[^\])]*)[\])]", re.IGNORECASE)
# "[Q&A 17]", "[Q&A Nr. 17; DR 2.3, S. 4]": Eintrag der Q&A-Liste im Datenraum
_QA_RE = re.compile(r"Q\s*&\s*A\s*(?:Nr\.?|Frage)?\s*(\d{1,4})\b", re.IGNORECASE)
_CITE_RE = re.compile(
    r"(?:DR|VDR|Datenraum|Data\s*Room)\s*(\d+(?:\.\d+)*)"
    r"(?:\s*,?\s*(?:S\.|Seite|Seiten|p\.|pp\.|page)\s*(\d+)(?:\s*[-–]\s*(\d+))?)?",
    re.IGNORECASE,
)

_ABBREVIATIONS = {
    "s", "mio", "mrd", "mia", "art", "abs", "nr", "ca", "bzw", "inkl", "exkl", "fr", "sfr", "dr",
    "prof", "z.b", "u.a", "d.h", "ggf", "resp", "lit", "ziff", "rz", "gem", "vgl", "sog", "tsd",
    "evtl", "max", "min", "zzgl", "abzgl", "insb", "bspw", "usw", "etc", "vs", "p", "pp", "jan",
    "feb", "mär", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dez", "st", "co",
}
# "CHF 4.2 Mio. Langfristige ..." beendet den Satz, "CHF 4.2 Mio. CHF" nicht.
_SCALE_WORDS = {"mio", "mrd", "mia", "tsd"}
_CURRENCY_WORDS = {"CHF", "EUR", "USD", "FRANKEN", "EURO"}
# Satzende vor Grossbuchstaben, und nach einer Klammer immer: "[DR 2.2, S. 3]. 2023 erzielte …"
_SPLIT_RE = re.compile(r"[.!?](?=\s+[\"„(]?[A-ZÄÖÜ])|(?<=[\])])[.!?](?=\s+\S)")


# „…“, “…”, «…», "…": wörtliche Zitate ab vier Wörtern; kürzere sind meist Namen oder Begriffe.
_QUOTE_RE = re.compile(r"„([^“”\"]+)[“”\"]|“([^”]+)”|«([^»]+)»|(?<![\w])\"([^\"]+)\"")


def quotes(text: str) -> list[str]:
    out = []
    for m in _QUOTE_RE.finditer(text):
        q = next(g for g in m.groups() if g is not None).strip()
        if len(q.split()) >= 4:
            out.append(q)
    return out


def parse_citations(text: str) -> list[Citation]:
    citations = []
    for bracket in _BRACKET_RE.finditer(text):
        found = []
        for m in _CITE_RE.finditer(bracket.group(1)):
            page_from = int(m.group(2)) if m.group(2) else None
            page_to = int(m.group(3)) if m.group(3) else page_from
            found.append((m.start(), Citation(m.group(1), page_from, page_to, m.group(0))))
        for m in _QA_RE.finditer(bracket.group(1)):
            found.append((m.start(), Citation(f"Q&A {int(m.group(1))}", None, None, m.group(0))))
        citations += [c for _, c in sorted(found, key=lambda x: x[0])]
    return citations


def strip_citations(text: str) -> str:
    text = re.sub(r"\s+([.,;:])", r"\1", _BRACKET_RE.sub("", text))
    return re.sub(r"(?<!\.)\.\.(?!\.)", ".", text).strip()  # "Mio. [DR 1]." -> "Mio."


def split_sentences(text: str) -> list[str]:
    sentences, start = [], 0
    for m in _SPLIT_RE.finditer(text):
        word = re.search(r"(\S+)$", text[start : m.start()])
        prev = word.group(1).lower().lstrip("([„\"") if word else ""
        nxt = re.match(r"\s+(\S+)", text[m.end() :])
        next_word = nxt.group(1).lower().strip(",") if nxt else ""
        scale_end = prev in _SCALE_WORDS and next_word.upper() not in _CURRENCY_WORDS
        if (prev in _ABBREVIATIONS and not scale_end) or (len(prev) == 1 and prev.isalpha()):
            continue
        if prev.isdigit() and next_word in MONTHS:
            continue
        sentences.append(text[start : m.end()].strip())
        start = m.end()
    rest = text[start:].strip()
    if rest:
        sentences.append(rest)
    return sentences


def _blocks(text: str):
    """Absätze und Aufzählungspunkte, mit der jeweils aktuellen Überschrift."""
    section, buffer = "", []
    for line in text.splitlines() + [""]:
        stripped = line.strip()
        heading = re.match(r"^#{1,6}\s+(.*)", stripped)
        bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)", stripped)
        if heading or bullet or not stripped or stripped.startswith("|"):
            if buffer:
                yield section, " ".join(buffer)
                buffer = []
        if heading:
            section = heading.group(1).strip()
        elif bullet:
            buffer = [bullet.group(1)]
        elif stripped and not stripped.startswith("|"):
            buffer.append(stripped)


def parse_report(text: str) -> list[Claim]:
    claims: list[Claim] = []
    for section, block in _blocks(text):
        previous = ""
        for sentence in split_sentences(block):
            citations = parse_citations(sentence)
            clean = strip_citations(sentence)
            facts = extract_facts(clean)
            if citations or facts:
                claims.append(Claim(len(claims) + 1, sentence, clean, section, citations, facts, previous))
            previous = clean
    return claims


def report_text(data: bytes, suffix: str) -> str:
    """Berichtstext aus PDF, Word oder Text."""
    if suffix in (".pdf", ".docx"):
        return "\n\n".join(read_pages(data, suffix))
    return data.decode("utf-8", errors="replace")


def load_report(path: str | Path) -> tuple[str, bytes]:
    path = Path(path)
    data = path.read_bytes()
    return report_text(data, path.suffix.lower()), data
