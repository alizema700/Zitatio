"""Zeilen und Spalten auf Datenraum-Seiten: Zu welcher Grösse und welcher Periode gehört ein Wert?

Eine Jahresrechnung schreibt "Materialaufwand 10'912'000 10'243'000" unter den Kopf
"Erfolgsrechnung 2025 und 2024". Erst mit Zeile und Spalte lässt sich prüfen, ob der
Bericht den Wert des richtigen Jahres und der richtigen Position nennt, und ob zwei
Dokumente für dieselbe Grösse dasselbe sagen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .facts import AMOUNT, MONTHS, Fact, page_facts

YEAR_RE = re.compile(r"(?<![\d'’])((?:19|20)\d{2})(?![\d'’]|[.,]\d)")
_MONTH_YEAR_RE = re.compile(rf"\b({'|'.join(MONTHS)})\s+((?:19|20)\d{{2}})\b", re.IGNORECASE)
_PERIOD_WORDS = re.compile(r"\b(per|bis|stichtag|abschluss|erfolgsrechnung|bilanz|jahresrechnung|geschäftsjahr"
                           r"|au|exercice|compte de résultat|comptes annuels|al|esercizio|conto economico)\b", re.I)
_PLAN_RE = re.compile(r"budget|businessplan|planung|plan-|forecast|prognose|hochrechnung|\bplan\b"
                      r"|prévision|plan d'affaires|preventivo|previsione", re.I)
_DATE_RE = re.compile(r"\b\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\b")

# Grössen, die DD-Berichte und Datenräume immer wieder nennen. Reihenfolge: spezifische zuerst,
# damit "bereinigtes EBITDA" nicht als EBITDA und "steuerbarer Reingewinn" nicht als Jahresgewinn gilt.
METRICS: list[tuple[str, str, re.Pattern]] = [
    (key, label, re.compile(rx, re.IGNORECASE))
    for key, label, rx in [
        ("ebitda_bereinigt", "bereinigtes EBITDA",
         r"bereinigt\w*\s+ebitda|ebitda\s*\(?\s*bereinigt|adjusted\s+ebitda|normalisiert\w*\s+ebitda"
         r"|ebitda\s+(?:ajusté|normalisé|rettificato|normalizzato)"),
        ("steuerbarer_gewinn", "steuerbarer Reingewinn",
         r"steuerbar\w*\s+(?:rein)?gewinn\w*|bénéfice imposable|utile imponibile"),
        ("ebitda", "EBITDA", r"\bebitda\b(?![-\s]*marge)"),
        ("ebit", "EBIT", r"\bebit\b(?![-\s]*marge)|\bbetriebsergebnis\w*|résultat d'exploitation|risultato operativo"),
        ("umsatz", "Umsatz", r"\bnettoerl[öo]s\w*|\b(?:netto)?ums[aä]tz(?!steuer)\w*|\berl[öo]s\w* aus lieferungen"
         r"|chiffre d'affaires|produits nets|ricavi netti|\bricavi\b|cifra d'affari|fatturato"),
        ("jahresgewinn", "Jahresgewinn", r"\bjahresgewinn\w*|\breingewinn\w*|\bjahresergebnis\w*|gewinn nach steuern"
         r"|bénéfice (?:net|de l'exercice|annuel)|résultat (?:net|de l'exercice)|utile (?:netto|d'esercizio|dell'esercizio)"),
        ("materialaufwand", "Materialaufwand", r"\bmaterialaufwand\w*|\bwarenaufwand\w*|charges de matériel|charges de marchandises|costi (?:del|per il) materiale"),
        ("personalaufwand", "Personalaufwand", r"\bpersonalaufwand\w*|charges de personnel|costi (?:del|per il) personale"),
        ("abschreibungen", "Abschreibungen", r"\babschreibung\w*|\bamortissements?\b|\bammortament\w*"),
        ("finanzaufwand", "Finanzaufwand", r"\bfinanzaufwand\w*|\bzinsaufwand\w*|charges financières|oneri finanziari"),
        ("fluessige_mittel", "flüssige Mittel", r"\bfl[üu]ssig\w*\s+mittel|liquidités|liquidità"),
        ("eigenkapital", "Eigenkapital", r"\beigenkapital\w*|fonds propres|capitale proprio"),
        ("aktienkapital", "Aktienkapital", r"\baktienkapital\w*|\bstammkapital\w*|capital[- ]actions|capital social|capitale azionario"),
        ("nettoverschuldung", "Nettoverschuldung", r"\bnettoverschuldung\w*|\bnet debt\b|endettement net|indebitamento netto"),
        ("finanzschulden", "verzinsliche Verbindlichkeiten",
         r"\bfinanzverbindlichkeit\w*|\bverzinslich\w*\s+verbindlichkeit\w*|\bbankschulden\b"),
        ("auftragsbestand", "Auftragsbestand", r"\bauftragsbestand\w*"),
        ("investitionen", "Investitionen", r"\binvestition\w*|\bcapex\b"),
    ]
]
LABELS = {key: label for key, label, _ in METRICS}
# Bestandesgrössen ohne Periode: Handelsregister und Statuten nennen das Aktienkapital ohne Jahr.
TIMELESS = {"aktienkapital"}


def metrics_in(text: str) -> list[tuple[str, int, int]]:
    """Genannte Grössen mit Position, ohne Überlappungen (spezifische gewinnen)."""
    taken: list[tuple[str, int, int]] = []
    for key, _, rx in METRICS:
        for m in rx.finditer(text):
            if not any(m.start() < e and s < m.end() for _, s, e in taken):
                taken.append((key, m.start(), m.end()))
    return sorted(taken, key=lambda t: t[1])


def metric_of(text: str) -> str | None:
    found = metrics_in(text)
    return found[0][0] if found else None


def years_in(text: str) -> list[int]:
    out = []
    for m in YEAR_RE.finditer(text):
        y = int(m.group(1))
        if y not in out:
            out.append(y)
    return out


def is_plan(text: str) -> bool:
    return bool(_PLAN_RE.search(text))


@dataclass(frozen=True)
class Cell:
    fact: Fact
    line: int  # Zeilennummer auf der Seite
    label: str  # Zeilenbeschriftung, z. B. "Nettoerlöse aus Lieferungen und Leistungen"
    metric: str | None
    year: int | None
    period: str | None  # "2025" oder "März 2025"; None, wenn unbekannt
    column: bool  # Jahr kommt aus einem Spaltenkopf mit mehreren Jahren
    plan: bool

    @property
    def tabular(self) -> bool:
        """Kurze Zeilenbeschriftung wie in einer Tabelle, kein Fliesstext."""
        return len(self.label) <= 60


@dataclass
class _Header:
    years: list[int]
    months: dict[int, str]  # Jahr -> Monatsname, wenn der Kopf einen Monat nennt
    plan: bool


def _header(line: str, has_amounts: bool) -> _Header | None:
    years = years_in(line)
    if not years or has_amounts:
        return None
    if len(line) > 90 and ";" not in line:
        return None  # Fliesstext ist kein Tabellenkopf
    if _DATE_RE.search(line) and not _PERIOD_WORDS.search(line):
        return None  # "Eintragung: 14.03.2011" ist ein Wert, kein Kopf
    months = {int(m.group(2)): m.group(1).capitalize() for m in _MONTH_YEAR_RE.finditer(line)}
    return _Header(years, months, is_plan(line))


def _clean_label(text: str) -> str:
    text = re.sub(r"\b(CHF|EUR|USD|TCHF|TEUR|Fr\.)\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" :;,-–\t")
    return text.rstrip("(").strip() if text.count("(") > text.count(")") else text


@lru_cache(maxsize=65536)
def page_cells(text: str, default_year: int | None = None, plan_doc: bool = False) -> tuple[Cell, ...]:
    """Jeder Betrag einer Seite mit Zeilenbeschriftung, Grösse und Periode."""
    facts = [f for f in page_facts(text) if f.kind == AMOUNT]
    cells: list[Cell] = []
    header: _Header | None = None
    pos = 0
    for n, line in enumerate(text.split("\n")):
        start, end = pos, pos + len(line)
        pos = end + 1
        row = [f for f in facts if start <= f.start < end]
        head = _header(line, bool(row))
        if head:
            header = head
            continue
        if not row:
            continue
        row_label, prev = "", start
        labels = []
        for f in row:
            segment = text[prev : f.start]
            if not row_label and re.search(r"[A-Za-zÄÖÜäöü]{3}", segment):
                row_label = segment
            labels.append(segment if re.search(r"[A-Za-zÄÖÜäöü]{3}", segment) else row_label)
            prev = f.end
        for i, (f, segment) in enumerate(zip(row, labels)):
            label = _clean_label(segment)
            metric = metric_of(label)
            own = years_in(label)
            year, column, period = None, False, None
            if len(own) == 1:
                year = own[0]
            elif header and len(header.years) == len(row) > 1:
                year, column = header.years[i], True
            elif header and len(header.years) == 1:
                year = header.years[0]
            elif default_year and not own:
                year = default_year
            if year is not None:
                month = header.months.get(year) if header and not own else None
                period = f"{month} {year}" if month else str(year)
            plan = plan_doc or bool(header and header.plan) or is_plan(label)
            cells.append(Cell(f, n, label, metric, year, period, column, plan))
    return tuple(cells)


def cell_at(cells: tuple[Cell, ...], fact: Fact) -> Cell | None:
    for c in cells:
        if c.fact.start == fact.start and c.fact.end == fact.end:
            return c
    return None


def doc_cells(doc, page: int) -> tuple[Cell, ...]:
    """Zellen einer Dokumentseite; Jahr und Plan-Kennzeichen des Titels gelten als Vorgabe."""
    years = years_in(doc.title)
    return page_cells(doc.pages[page - 1], years[0] if len(years) == 1 else None, is_plan(doc.title))
