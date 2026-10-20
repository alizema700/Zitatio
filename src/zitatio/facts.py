"""Extraktion und Normalisierung prüfbarer Fakten (Beträge, Daten, Prozente, Fristen, UID).

Alles hier ist deterministisch: Zwei Schreibweisen desselben Werts
("CHF 3.5 Mio." und "CHF 3'500'000") ergeben denselben normalisierten Wert.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from functools import lru_cache

AMOUNT, DATE, PERCENT, DURATION, UID = "betrag", "datum", "prozent", "frist", "uid"

KIND_LABELS = {
    AMOUNT: "Betrag",
    DATE: "Datum",
    PERCENT: "Prozent",
    DURATION: "Frist",
    UID: "UID",
}


@dataclass(frozen=True)
class Fact:
    kind: str
    value: object  # normalisiert und hashbar
    text: str  # Originalschreibweise
    start: int
    end: int
    # Rundungsschritt der Schreibweise: "CHF 18.45 Mio." ist auf 10'000 genau.
    precision: Decimal | None = field(default=None, compare=False)
    # Einheit aus dem Seitenkopf, wenn die Zahl ohne Währung in einer Tabelle steht.
    unit: str | None = field(default=None, compare=False)

    def matches(self, other: "Fact") -> bool:
        return self.kind == other.kind and self.value == other.value

    def match(self, found: "Fact") -> str | None:
        """'exakt', 'gerundet' (diese Schreibweise rundet den gefundenen Wert) oder None."""
        if self.kind != found.kind:
            return None
        if self.value == found.value:
            return "exakt"
        if not self.precision:
            return None
        if self.kind == AMOUNT:
            (cur, mine), (other_cur, theirs) = self.value, found.value
            if cur != other_cur or not theirs:
                return None
            close = abs(mine - theirs) <= self.precision / 2 and abs(mine - theirs) / abs(theirs) <= Decimal("0.01")
            return "gerundet" if close else None
        if self.kind == PERCENT:
            return "gerundet" if abs(self.value - found.value) <= self.precision / 2 else None
        return None

    def display(self) -> str:
        return format_value(self.kind, self.value)


# --- Zahlen -----------------------------------------------------------------

_NUM = (
    # ein Trennzeichen pro Zahl: "187'400 201'300" sind zwei Tabellenwerte, nicht einer
    r"\d{1,3}(?:'\d{3})+(?:[.,]\d+)?"  # 1'250'000.50
    r"|\d{1,3}(?:’\d{3})+(?:[.,]\d+)?"
    r"|\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?"  # 1 250 000, auch mit geschütztem Leerzeichen
    r"|\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?"  # 1.250.000,00
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # 1,250,000.00
    r"|\d+(?:[.,]\d+)?"
)
_SCALE = (r"Mio\.?|Millionen|Millions|Million|Milioni|Mrd\.?|Milliarden|Milliards|Miliardi|Mia\.?|Tsd\.?"
          r"|mio\.?|millions|milioni|milliards|miliardi|mrd\.?"
          r"|k(?![A-Za-zÄÖÜäöü])")
_CUR = r"CHF|SFr\.?|Fr\.|EUR|€|USD|US\$|\$|TCHF|TEUR|kCHF"

_SCALE_FACTORS = {"mio": 10**6, "million": 10**6, "millionen": 10**6, "millions": 10**6, "milioni": 10**6,
                  "mrd": 10**9, "milliarden": 10**9, "milliards": 10**9, "miliardi": 10**9, "mia": 10**9, "tsd": 10**3, "k": 10**3}
_CURRENCIES = {"chf": ("CHF", 1), "sfr": ("CHF", 1), "fr": ("CHF", 1), "eur": ("EUR", 1),
               "€": ("EUR", 1), "usd": ("USD", 1), "us$": ("USD", 1), "$": ("USD", 1),
               "tchf": ("CHF", 1000), "teur": ("EUR", 1000), "kchf": ("CHF", 1000)}


def parse_number(raw: str, scaled: bool = False) -> Decimal | None:
    """Liest Schweizer, deutsche und englische Zahlenformate."""
    s = re.sub(r"['’ \u00a0\u202f]", "", raw.strip())
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) > 2 or (len(parts[1]) == 3 and not scaled):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts[1]) == 3 and not scaled):
            s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _norm_decimal(d: Decimal) -> Decimal:
    return d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize()


def _scale_factor(scale: str | None) -> int:
    if not scale:
        return 1
    return _SCALE_FACTORS.get(scale.lower().rstrip("."), 1)


def _currency(cur: str) -> tuple[str, int]:
    return _CURRENCIES.get(cur.lower().rstrip("."), (cur.upper(), 1))


_AMOUNT_RE = re.compile(
    rf"(?<![\w$€])(?P<c1>{_CUR})\s*(?P<n1>{_NUM})(?:\s*(?P<s1>{_SCALE}))?(?:\.[-–]{{1,2}})?"
    rf"|(?<![\w.,'’])(?P<n2>{_NUM})(?:\s*(?P<s2>{_SCALE}))?\s*(?P<c2>{_CUR})(?![A-Za-z])"
)


def _amounts(text: str):
    for m in _AMOUNT_RE.finditer(text):
        cur, num, scale = (m["c1"], m["n1"], m["s1"]) if m["c1"] else (m["c2"], m["n2"], m["s2"])
        value = parse_number(num, scaled=bool(scale))
        if value is None:
            continue
        code, cur_factor = _currency(cur)
        factor = _scale_factor(scale) * cur_factor
        precision = _step(num) * factor if factor > 1 else None
        value = _norm_decimal(value * factor)
        yield Fact(AMOUNT, (code, value), m.group(0).strip(), m.start(), m.end(), precision)


def _step(num: str) -> Decimal:
    """Kleinster Schritt einer geschriebenen Zahl: "18.45" -> 0.01, "3" -> 1."""
    m = re.search(r"[.,](\d{1,2})$", num.strip())
    return Decimal(1).scaleb(-len(m.group(1))) if m else Decimal(1)


# --- Daten ------------------------------------------------------------------

MONTHS = {"januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6,
          "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
          # Französisch und Italienisch: Datenräume aus der Romandie und dem Tessin
          "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "juin": 6, "juillet": 7, "août": 8,
          "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
          "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
          "agosto": 8, "settembre": 9, "ottobre": 10, "dicembre": 12}
_MONTH_RE = "|".join(MONTHS)

_DATE_RES = [
    (re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b"), "dmy"),
    (re.compile(rf"\b(\d{{1,2}})(?:\.|er|°|º)?\s*({_MONTH_RE})\s+(\d{{4}})\b", re.IGNORECASE), "dMy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]


def _dates(text: str):
    for rx, order in _DATE_RES:
        for m in rx.finditer(text):
            a, b, c = m.groups()
            try:
                if order == "dmy":
                    d = dt.date(int(c), int(b), int(a))
                elif order == "dMy":
                    d = dt.date(int(c), MONTHS[b.lower()], int(a))
                else:
                    d = dt.date(int(a), int(b), int(c))
            except ValueError:
                continue
            yield Fact(DATE, d, m.group(0), m.start(), m.end())


# --- Prozente ---------------------------------------------------------------

_PERCENT_RE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s?(?:%|Prozent\b|pct\.?)")


def _percents(text: str):
    for m in _PERCENT_RE.finditer(text):
        raw = m.group(1).replace(",", ".")
        decimals = len(raw.partition(".")[2])
        # "12.4 %" darf 12.38 % runden; "2 %" für 2.4 % wäre eine Abweichung, kein Runden
        yield Fact(PERCENT, _norm_decimal(Decimal(raw)), m.group(0), m.start(), m.end(),
                   Decimal(1).scaleb(-decimals) if decimals else None)


# --- Fristen ----------------------------------------------------------------

NUMBER_WORDS = {"ein": 1, "eine": 1, "einem": 1, "einen": 1, "einer": 1, "zwei": 2, "drei": 3,
                "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
                "elf": 11, "zwölf": 12, "achtzehn": 18, "vierundzwanzig": 24, "dreissig": 30,
                "dreißig": 30, "sechzig": 60, "neunzig": 90,
                "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "six": 6, "douze": 12,
                "uno": 1, "due": 2, "tre": 3, "quattro": 4, "sei": 6, "dodici": 12}
_UNITS = {"tag": "Tage", "woche": "Wochen", "monat": "Monate", "jahr": "Jahre",
          "jour": "Tage", "semaine": "Wochen", "mois": "Monate", "an": "Jahre", "année": "Jahre",
          "giorn": "Tage", "settiman": "Wochen", "mes": "Monate", "ann": "Jahre"}
_DURATION_RE = re.compile(
    r"\b(?:(Tag|Woche|Monat|Jahr)(?:e|en|es|s|n)?"
    r"|(jour|semaine|année|an)s?|(mois)"
    r"|(giorn(?=[io])|settiman(?=[ae])|mes(?=[ie])|ann(?=[io]))[aeio])\b",
    re.IGNORECASE,
)
# Zahl vor der Einheit: zuerst die (seltenen) Einheiten finden, dann rückwärts die Zahl lesen
_COUNT_BEFORE = re.compile(r"(?<![\w.,'’])(\d+|[a-zäöüéèß]{2,14})\s*[- ]?\s*$", re.IGNORECASE)


def _durations(text: str):
    for m in _DURATION_RE.finditer(text):
        before = _COUNT_BEFORE.search(text, max(0, m.start() - 20), m.start())
        if not before:
            continue
        raw_n, unit = before.group(1).lower(), next(g for g in m.groups() if g).lower()
        if not raw_n.isdigit() and raw_n not in NUMBER_WORDS:
            continue
        n = int(raw_n) if raw_n.isdigit() else NUMBER_WORDS[raw_n]
        yield Fact(DURATION, (n, _UNITS[unit]), text[before.start() : m.end()], before.start(), m.end())


# --- UID (Unternehmens-Identifikationsnummer) --------------------------------

_UID_RE = re.compile(r"\bCHE[-\s]?(\d{3})\.?(\d{3})\.?(\d{3})\b")
_UID_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4)


def uid_is_valid(uid: str) -> bool:
    """Prüft die Prüfziffer (Modulo 11) einer UID im Format CHE-123.456.789."""
    digits = re.sub(r"\D", "", uid)
    if len(digits) != 9:
        return False
    check = 11 - sum(int(d) * w for d, w in zip(digits[:8], _UID_WEIGHTS)) % 11
    if check == 11:
        check = 0
    return check != 10 and check == int(digits[8])


def _uids(text: str):
    for m in _UID_RE.finditer(text):
        a, b, c = m.groups()
        yield Fact(UID, f"CHE-{a}.{b}.{c}", m.group(0), m.start(), m.end())


# --- Öffentliche Funktionen -------------------------------------------------

_EXTRACTORS = (_uids, _dates, _amounts, _percents, _durations)  # Reihenfolge = Priorität


def extract_facts(text: str) -> list[Fact]:
    """Alle prüfbaren Fakten eines Texts, ohne Überlappungen, in Textreihenfolge."""
    taken: list[Fact] = []
    for extractor in _EXTRACTORS:
        for fact in extractor(text):
            if not any(fact.start < t.end and t.start < fact.end for t in taken):
                taken.append(fact)
    return sorted(taken, key=lambda f: f.start)


# --- Tabellen ohne Währung ---------------------------------------------------
# Jahresrechnungen und Excel-Tabellen nennen die Einheit einmal im Kopf ("in CHF",
# "in TCHF", "in Mio. CHF") und die Zahlen dann ohne Währung.

_CODE = r"(CHF|EUR|USD)"
_UNIT_RES = [
    (re.compile(r"\b(T|k)(CHF|EUR|USD)\b"), 1000),
    (re.compile(rf"\bin\s+Tausend\s+{_CODE}\b|\b{_CODE}\s*['’]?000\b|\bin\s+{_CODE}\s+1['’]000\b"
                rf"|\ben\s+milliers\s+de\s+{_CODE}\b|\bin\s+migliaia\s+di\s+{_CODE}\b", re.I), 1000),
    (re.compile(rf"\bin\s+(?:Mio\.?|Millionen)\s*{_CODE}\b|\b{_CODE}\s+(?:Mio\.|Millionen)(?!\s*\d)"
                rf"|\ben\s+millions\s+de\s+{_CODE}\b|\bin\s+milioni\s+di\s+{_CODE}\b", re.I), 10**6),
    (re.compile(rf"\b(?:in|en|Beträge in|Währung:?|montants en|importi in|valuta:?)\s+{_CODE}\b(?!\s*[\d'’])", re.I), 1),
]
# US-Berichte (10-K): "(In millions, except per share data)", "(Dollars in thousands)", "(Millions)".
# Die Währung steht dort nur als "$" in der Tabelle.
_EN_UNIT_RE = re.compile(
    r"(?<!shares )(?<!share )\b(?:in|In|IN)\s+(millions|thousands|billions)\b|\((Millions|Thousands|Billions|millions|thousands)\)"
)
_EN_FACTORS = {"thousands": 1000, "millions": 10**6, "billions": 10**9}
_BARE_RE = re.compile(rf"(?<![\w.,'’/-])\(?-?(?P<n>{_NUM})\)?(?![\w%'’]|[.,]\d)")


def page_unit(text: str) -> tuple[str, int] | None:
    """Die eine Einheit, die der Seitenkopf für Zahlen ohne Währung angibt; sonst None."""
    found = set()
    for rx, factor in _UNIT_RES:
        for m in rx.finditer(text):
            code = next(g for g in reversed(m.groups()) if g and g.upper() in ("CHF", "EUR", "USD"))
            found.add((code.upper(), factor))
    if not found and re.search(r"\$|U\.S\. dollars|USD", text):
        for m in _EN_UNIT_RE.finditer(text):
            found.add(("USD", _EN_FACTORS[(m.group(1) or m.group(2)).lower()]))
    if len(found) == 1:
        return found.pop()
    # "in CHF" und "TCHF" auf derselben Seite: nicht eindeutig
    return None


@lru_cache(maxsize=65536)
def page_facts(text: str) -> tuple[Fact, ...]:
    """Fakten einer Datenraum-Seite inklusive Tabellenzahlen in der Einheit des Seitenkopfs."""
    facts = extract_facts(text)
    unit = page_unit(text)
    if unit is None:
        return tuple(facts)
    code, factor = unit
    label = {1: code, 1000: f"T{code}", 10**6: f"Mio. {code}", 10**9: f"Mrd. {code}"}[factor]
    extra = []
    if factor > 1:
        # "$ 5,363" in einer Tabelle "(in millions)" heisst USD 5'363 Mio.; beide Lesarten behalten
        for f in facts:
            if f.kind == AMOUNT and f.value[0] == code and not re.search(_SCALE, f.text) \
                    and not re.match(r"[TtKk]", f.text):
                num = re.search(_NUM, f.text).group(0)
                extra.append(Fact(AMOUNT, (code, _norm_decimal(f.value[1] * factor)), f.text, f.start, f.end,
                                  _step(num) * factor, label))
    for m in _BARE_RE.finditer(text):
        start, end = m.span("n")
        if any(start < f.end and f.start < end for f in facts):
            continue
        num = m["n"]
        if re.fullmatch(r"\d{1,2}\.\d{1,2}", num) and text[end : end + 1] == ".":
            continue  # "Auftragsbestand 31.12." ist ein Stichtag
        value = parse_number(num)
        if value is None or value == 0:
            continue
        plain = re.fullmatch(r"\d+", num) is not None
        if plain and (value < 100 or 1900 <= value <= 2100):
            continue  # Jahreszahlen, Anmerkungsnummern, Zeilennummern
        precision = _step(num) * factor if factor > 1 else None  # "18'450" in TCHF ist auf 1'000 genau
        extra.append(Fact(AMOUNT, (code, _norm_decimal(value * factor)), num, start, end, precision, label))
    return tuple(sorted(facts + extra, key=lambda f: f.start))


def format_value(kind: str, value) -> str:
    if kind == AMOUNT:
        cur, amount = value
        whole, _, frac = f"{amount:f}".partition(".")
        grouped = f"{int(whole):,}".replace(",", "'")
        return f"{cur} {grouped}" + (f".{frac}" if frac else "")
    if kind == DATE:
        return value.strftime("%d.%m.%Y")
    if kind == PERCENT:
        return f"{value} %"
    if kind == DURATION:
        n, unit = value
        return f"{n} {unit}"
    return str(value)
