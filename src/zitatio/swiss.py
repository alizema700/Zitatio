"""Schweizer Prüfungen, die über "steht es auf der Seite?" hinausgehen.

- Zeichnungsberechtigung: Wer einen Vertrag für die Gesellschaft unterschrieben hat, wird gegen den
  Handelsregisterauszug geprüft (Einzelunterschrift, Kollektivunterschrift zu zweien, Prokura).
- Kapitalschutz nach Art. 725a/725b OR: Kapitalverlust und Überschuldung aus der letzten Bilanz.
- Revisionspflicht nach Art. 727 OR: ordentliche oder eingeschränkte Revision.
- Vorsorge: Unterdeckung der Pensionskasse.
- Aktienbuch gegen Handelsregister: Stimmt die Zahl der Aktien?
- Fusionskontrolle nach Art. 9 KG und Lex Koller als Hinweise für das Deal-Team.
- Gesetzliche Sätze im Bericht (MWST, Verrechnungssteuer, Emissionsabgabe, AHV, BVG, Bundessteuer).

Alles ist regelbasiert und nennt die Fundstelle oder den Gesetzesartikel.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .dataroom import DataRoom, Document
from .facts import PERCENT, format_value
from .tables import doc_cells, years_in
from .verify import Evidence, Finding, Status, _evidence

WARNUNG, HINWEIS, OK = "warnung", "hinweis", "ok"


def _n(x) -> str:
    return f"{int(x):,}".replace(",", "'")


@dataclass
class Flag:
    level: str  # warnung, hinweis, ok
    area: str
    title: str
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)  # Indexnummern, für die Auswertung


# --- Handelsregister ----------------------------------------------------------------

_SIGN_KINDS = (r"Einzelunterschrift|Kollektivunterschrift zu zweien|Einzelprokura|Kollektivprokura zu zweien"
               r"|ohne Zeichnungsberechtigung"
               # Handelsregister der Romandie und des Tessins
               r"|signature individuelle|signature collective à deux|procuration individuelle"
               r"|procuration collective à deux|sans droit de signature"
               r"|firma individuale|firma collettiva a due|procura individuale|procura collettiva a due"
               r"|senza diritto di firma")
_SIGN_RE = re.compile(rf"(?:mit\s+|avec\s+|con\s+)?({_SIGN_KINDS})", re.IGNORECASE)
_UPPER, _LOWER = "A-ZÄÖÜÉÈÀÇ", "a-zäöüéèêàçëïôîù"
_PERSON_START = re.compile(rf"[{_UPPER}][{_LOWER}\-]+, (?:Dr\. |Prof\. )?[{_UPPER}][{_LOWER}\-]+(?: [{_UPPER}][{_LOWER}\-]+)?,")
_TITLES = {"dr", "prof", "lic", "iur", "med"}
# Satzende, aber nicht nach Abkürzungen wie "Dr." oder "St."
_SENTENCE_END = re.compile(rf"(?:\b[{_LOWER}]\w*|\w{{5,}})[.:]\s+[{_UPPER}]")


def _name_tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(rf"[{_LOWER}\-]{{2,}}", name.lower()) if w not in _TITLES)


@dataclass
class Signatory:
    name: str
    tokens: frozenset[str]
    kind: str  # wie im Register
    doc: Document
    page: int
    start: int
    end: int

    @property
    def alone(self) -> bool:
        return bool(re.match(r"einzel|signature individuelle|procuration individuelle|firma individuale|procura individuale",
                             self.kind.lower()))

    @property
    def authorised(self) -> bool:
        return not re.match(r"ohne|sans|senza", self.kind.lower())


def _register_doc(room: DataRoom) -> Document | None:
    return next((d for d in room.documents
                 if d.index and re.search(r"handelsregister|registre du commerce|registro di commercio", d.title, re.I)),
                None)


def signatories(room: DataRoom) -> list[Signatory]:
    doc = _register_doc(room)
    if not doc:
        return []
    out = []
    for page_no, text in enumerate(doc.pages, 1):
        flat = text.replace("\n", " ")
        prev = 0
        for m in _SIGN_RE.finditer(flat):
            chunk = flat[prev : m.start()]
            prev = m.end()
            # Der Eintrag beginnt mit "Name, Vorname," nach dem letzten Satzende
            starts = [c for c in _PERSON_START.finditer(chunk)
                      if not _SENTENCE_END.search(chunk[c.start():])]
            if not starts:
                continue
            s = starts[0]
            surname, given = [p.strip() for p in s.group(0).rstrip(",").split(",", 1)]
            name = f"{given} {surname}"
            out.append(Signatory(name, _name_tokens(name), m.group(1), doc, page_no,
                                 m.start() - len(chunk) + s.start(), m.end()))
    return out


def company_name(room: DataRoom) -> str | None:
    doc = _register_doc(room)
    if not doc:
        return None
    m = re.search(r"(?:Firma|Raison sociale|Ditta):\s*([^\n]+)", "\n".join(doc.pages))
    return m.group(1).strip() if m else None


_SIGNED_RE = re.compile(r"(?:Für die|Für|Pour la|Pour|Per la|Per) ([^:\n]{3,80}):\s*([^\n]+)")


def _lookup(name: str, register: list[Signatory]) -> Signatory | None:
    tokens = _name_tokens(name)
    for s in register:
        if tokens and (tokens <= s.tokens or s.tokens <= tokens) and len(tokens & s.tokens) >= 2:
            return s
    return None


def check_signatures(room: DataRoom) -> list[Flag]:
    register, firm = signatories(room), company_name(room)
    if not register or not firm:
        return []
    key = re.sub(r"\W+", " ", firm.lower()).strip()
    flags, checked = [], 0
    for doc in room.documents:
        if doc.index is None or doc is register[0].doc:
            continue
        for page_no, text in enumerate(doc.pages, 1):
            for m in _SIGNED_RE.finditer(text):
                if key not in re.sub(r"\W+", " ", m.group(1).lower()):
                    continue
                checked += 1
                names = [n.split(",")[0].strip() for n in re.split(r";| und | et | e ", m.group(2)) if n.strip()]
                found = [(n, _lookup(n, register)) for n in names]
                where = f"{doc.label}, S. {page_no}"
                ev = [_evidence(doc, page_no, m.start(), m.end())]
                unknown = [n for n, s in found if s is None or not s.authorised]
                ok = [s for _, s in found if s is not None and s.authorised]
                if unknown:
                    flags.append(Flag(WARNUNG, "Zeichnungsberechtigung", f"{doc.label} {doc.title}",
                                      f"{', '.join(unknown)} unterschreibt für die {firm}, ist aber im Handelsregister "
                                      f"nicht als zeichnungsberechtigt eingetragen ({where}).", ev, [doc.index]))
                elif not any(s.alone for s in ok) and len(ok) < 2:
                    s = ok[0]
                    flags.append(Flag(WARNUNG, "Zeichnungsberechtigung", f"{doc.label} {doc.title}",
                                      f"{s.name} hat {s.kind}, unterschreibt aber allein für die {firm} ({where}). "
                                      "Der Vertrag bindet die Gesellschaft so möglicherweise nicht.",
                                      ev + [_evidence(s.doc, s.page, s.start, s.end)], [doc.index]))
    if checked and not flags:
        flags.append(Flag(OK, "Zeichnungsberechtigung", "Alle Unterschriften gedeckt",
                          f"{checked} Unterschriftenblöcke für die {firm} passen zum Handelsregister."))
    elif checked:
        flags.append(Flag(HINWEIS, "Zeichnungsberechtigung", "Geprüfte Unterschriften",
                          f"{checked} Unterschriftenblöcke für die {firm} gegen {len(register)} Einträge im "
                          f"Handelsregister geprüft."))
    return flags


# --- Bilanz: Kapitalschutz und Revisionspflicht ----------------------------------------

_ROWS = {
    "aktienkapital": r"^aktienkapital|^capital[- ]actions|^capitale azionario",
    "kapitalreserve": r"gesetzliche kapitalreserve|réserve légale issue du capital|riserva legale da capitale",
    "gewinnreserve": r"gesetzliche gewinnreserve|réserve légale issue du bénéfice|riserva legale da utili",
    "eigenkapital": r"^(?:total\s+)?(?:eigenkapital|fonds propres|capitale proprio)",
    "bilanzsumme": r"^(?:bilanzsumme|total aktiven|total passiven|total de l'actif|total du passif|totale attivi|totale passivi)",
    "umsatz": r"nettoerl[öo]s|^umsatz|chiffre d'affaires|produits nets|ricavi netti|cifra d'affari",
}


def _latest_statement(room: DataRoom) -> tuple[Document, int, dict] | None:
    """Neueste Jahresrechnung mit Bilanz: {Zeile: (Wert, Zelle)} aus der Spalte des Abschlussjahrs."""
    best = None
    for doc in room.documents:
        if not doc.index or not re.search(r"jahresrechnung|jahresabschluss|comptes annuels|états financiers|conto annuale|bilancio", doc.title, re.I):
            continue
        years = years_in(doc.title)
        if not years:
            continue
        values = {}
        for p in range(1, len(doc.pages) + 1):
            for cell in doc_cells(doc, p):
                label = cell.label.lower()
                for key, rx in _ROWS.items():
                    if key not in values and re.search(rx, label) and cell.year in (None, years[0]):
                        before = doc.pages[p - 1][max(0, cell.fact.start - 2) : cell.fact.start]
                        sign = -1 if re.search(r"[-−(]\s?$", before) else 1
                        values[key] = (sign * cell.fact.value[1], doc, p, cell)
        if "eigenkapital" in values and (best is None or years[0] > best[1]):
            best = (doc, years[0], values)
    return best


def check_capital(room: DataRoom) -> list[Flag]:
    found = _latest_statement(room)
    if not found:
        return []
    doc, year, v = found
    equity = v["eigenkapital"][0]
    ev = [_evidence(d, p, c.fact.start, c.fact.end) for _, d, p, c in v.values()]
    if "aktienkapital" not in v:
        reg = _register_doc(room)
        m = re.search(r"(?:Aktienkapital|Capital-actions|Capitale azionario):\s*CHF\s*([\d'’]+)", "\n".join(reg.pages)) if reg else None
        if not m:
            return []
        capital = Decimal(re.sub(r"['’]", "", m.group(1)))
        source = f"{reg.label} (Handelsregister)"
    else:
        capital, source = v["aktienkapital"][0], doc.label
    reserves = sum((v[k][0] for k in ("kapitalreserve", "gewinnreserve") if k in v), Decimal(0))
    half = (capital + reserves) / 2
    chf = lambda x: format_value("betrag", ("CHF", x))  # noqa: E731
    basis = f"Aktienkapital {chf(capital)} ({source})" + (f" und gesetzliche Reserven {chf(reserves)}" if reserves else "")
    if equity < 0:
        return [Flag(WARNUNG, "Kapitalschutz", f"Überschuldung per {year}",
                     f"Das Eigenkapital ist negativ ({chf(equity)}, {doc.label}). Nach Art. 725b OR muss der "
                     "Verwaltungsrat einen Zwischenabschluss erstellen und bei bestätigter Überschuldung das Gericht "
                     "benachrichtigen, ausser Gläubiger treten im Rang zurück.", ev, [doc.index])]
    if equity < half:
        return [Flag(WARNUNG, "Kapitalschutz", f"Kapitalverlust per {year}",
                     f"Das Eigenkapital von {chf(equity)} deckt die Hälfte von {basis} nicht mehr. Nach Art. 725a OR "
                     "muss der Verwaltungsrat Sanierungsmassnahmen ergreifen.", ev, [doc.index])]
    return [Flag(OK, "Kapitalschutz", f"Kein Kapitalverlust per {year}",
                 f"Eigenkapital {chf(equity)} gegenüber der Hälfte von {basis}: {chf(half)} (Art. 725a OR).", ev)]


def _fte(room: DataRoom, year: int) -> tuple[int, Document, int] | None:
    rx = re.compile(r"(\d{2,5})\s+(?:Vollzeitstellen|postes à plein temps|posti a tempo pieno)"
                    r"|Vollzeitstellen\D{0,30}(\d{2,5})|(?:FTE|EPT)\D{0,20}(\d{2,5})")
    for doc in room.documents:
        if doc.index and str(year) in doc.title:
            for p, text in enumerate(doc.pages, 1):
                m = rx.search(text)
                if m:
                    return int(next(g for g in m.groups() if g)), doc, p
    return None


def check_audit(room: DataRoom) -> list[Flag]:
    found = _latest_statement(room)
    if not found:
        return []
    doc, year, v = found
    tests = []
    if "bilanzsumme" in v:
        tests.append(("Bilanzsumme", v["bilanzsumme"][0], Decimal(20_000_000)))
    if "umsatz" in v:
        tests.append(("Umsatzerlös", v["umsatz"][0], Decimal(40_000_000)))
    fte = _fte(room, year)
    if fte:
        tests.append(("Vollzeitstellen im Jahresdurchschnitt", Decimal(fte[0]), Decimal(250)))
    if len(tests) < 2:
        return []
    over = [t for t in tests if t[1] >= t[2]]
    report = next((d for d in room.documents if d.index and re.search(r"revision", d.title, re.I)), None)
    limited = report and re.search(r"eingeschränkten Revision|contrôle restreint|revisione limitata", "\n".join(report.pages), re.I)
    def show(name: str, x: Decimal) -> str:
        return _n(x) if "stellen" in name.lower() else format_value("betrag", ("CHF", x))

    parts = ", ".join(f"{name} {show(name, val)} ({'über' if val >= limit else 'unter'} {show(name, limit)})"
                      for name, val, limit in tests)
    if len(over) >= 2 and limited:
        return [Flag(WARNUNG, "Revision", f"Ordentliche Revision {year} wohl nötig",
                     f"{parts}. Zwei von drei Grössen sind überschritten; nach Art. 727 OR braucht es eine ordentliche "
                     f"Revision, wenn das zwei Jahre nacheinander gilt. Vorliegend ist eine eingeschränkte Revision "
                     f"({report.label}).", [], [report.index])]
    kind = "eingeschränkte Revision genügt" if len(over) < 2 else "ordentliche Revision prüfen"
    return [Flag(OK if len(over) < 2 else HINWEIS, "Revision", f"Revisionspflicht {year}: {kind}",
                 f"{parts}. Art. 727 OR verlangt die ordentliche Revision ab zwei von drei Grössen "
                 "in zwei aufeinanderfolgenden Jahren.")]


# --- Vorsorge, Aktienbuch, Fusionskontrolle, Lex Koller ---------------------------------

def check_pension(room: DataRoom) -> list[Flag]:
    rx = re.compile(r"(?:Deckungsgrad|degré de couverture|grado di copertura)[^\n%]{0,80}?(\d{2,3}(?:[.,]\d+)?)\s?%", re.I)
    for doc in room.documents:
        if not doc.index:
            continue
        for p, text in enumerate(doc.pages, 1):
            m = rx.search(text)
            if not m:
                continue
            rate = Decimal(m.group(1))
            ev = [_evidence(doc, p, m.start(1), m.end(1))]
            if rate < 100:
                return [Flag(WARNUNG, "Vorsorge", f"Unterdeckung der Pensionskasse ({rate} %)",
                             f"Der Deckungsgrad liegt unter 100 % ({doc.label}, S. {p}). Sanierungsbeiträge von "
                             "Arbeitgeberin und Mitarbeitenden sind möglich (Art. 65d BVG).", ev, [doc.index])]
            return [Flag(OK, "Vorsorge", f"Deckungsgrad {rate} %",
                         f"Keine Unterdeckung der Vorsorgeeinrichtung ({doc.label}, S. {p}).", ev)]
    return []


def check_share_register(room: DataRoom) -> list[Flag]:
    reg = _register_doc(room)
    book = next((d for d in room.documents if d.index and re.search(r"aktienbuch|aktionärsverzeichnis|registre des actions|libro delle azioni", d.title, re.I)), None)
    if not reg or not book:
        return []
    m = re.search(r"(?:eingeteilt in|divisé en|suddiviso in) ([\d'’]+) (?:Namen|Inhaber)?(?:aktien|actions|azioni)", "\n".join(reg.pages))
    if not m:
        return []
    issued = int(re.sub(r"['’]", "", m.group(1)))
    held = [int(re.sub(r"['’]", "", x)) for x in re.findall(r":\s*([\d'’]+) (?:Namen|Inhaber)aktien", "\n".join(book.pages))]
    if not held:
        return []
    total = sum(held)
    if total == issued:
        return [Flag(OK, "Aktienbuch", "Aktienbuch vollständig",
                     f"Das Aktienbuch ({book.label}) verbucht {_n(total)} Aktien, wie im Handelsregister ({reg.label}).")]
    return [Flag(WARNUNG, "Aktienbuch", "Aktienbuch und Handelsregister weichen ab",
                 f"Das Aktienbuch ({book.label}) verbucht {_n(total)} Aktien, das Handelsregister ({reg.label}) nennt "
                 f"{_n(issued)}. Wem die übrigen Aktien gehören, ist für den Kauf entscheidend.",
                 [], [book.index])]


def check_merger_control(room: DataRoom) -> list[Flag]:
    found = _latest_statement(room)
    if not found or "umsatz" not in found[2]:
        return []
    doc, year, v = found
    revenue = v["umsatz"][0]
    chf = format_value("betrag", ("CHF", revenue))
    if revenue >= 100_000_000:
        text = (f"Die Zielgesellschaft erzielt {chf} ({doc.label}, {year}). Liegt davon mindestens CHF 100 Mio. in der "
                "Schweiz, ist der Zusammenschluss meldepflichtig, sobald ein weiterer Beteiligter ebenfalls CHF 100 Mio. "
                "in der Schweiz und alle zusammen CHF 2 Mrd. weltweit oder CHF 500 Mio. in der Schweiz erreichen "
                "(Art. 9 Abs. 1 KG).")
        return [Flag(HINWEIS, "Fusionskontrolle", "WEKO-Meldepflicht prüfen", text)]
    text = (f"Die Zielgesellschaft erzielt insgesamt {chf} ({doc.label}, {year}) und damit weniger als CHF 100 Mio. "
            "in der Schweiz. Erwirbt ein einzelner Käufer die Kontrolle, ist der Zusammenschluss nach Art. 9 Abs. 1 KG "
            "nicht meldepflichtig. Ausnahme: Für den Käufer wurde in einem Markt rechtskräftig eine marktbeherrschende "
            "Stellung festgestellt (Art. 9 Abs. 4 KG).")
    return [Flag(OK, "Fusionskontrolle", "Keine WEKO-Meldung nötig (ein Käufer)", text)]


def check_real_estate(room: DataRoom) -> list[Flag]:
    rx = re.compile(r"(?:Liegenschaften|Grundstücke|Immobilien|Grundeigentum)\s+([\d'’]{5,})")
    for doc in room.documents:
        if not doc.index or not re.search(r"jahresrechnung|comptes annuels|conto annuale", doc.title, re.I):
            continue
        for p, text in enumerate(doc.pages, 1):
            m = rx.search(text)
            if m and int(re.sub(r"['’]", "", m.group(1))) > 0:
                return [Flag(HINWEIS, "Lex Koller", "Grundeigentum in der Bilanz",
                             f"Die Gesellschaft hält Grundstücke ({doc.label}, S. {p}). Bei einem Käufer aus dem Ausland "
                             "ist die Bewilligungspflicht nach dem BewG zu prüfen; Betriebsstätten-Grundstücke sind "
                             "bewilligungsfrei (Art. 2 Abs. 2 lit. a BewG).",
                             [_evidence(doc, p, m.start(), m.end())], [doc.index])]
    return []


def swiss_flags(room: DataRoom) -> list[Flag]:
    flags = []
    for check in (check_signatures, check_capital, check_audit, check_pension, check_share_register,
                  check_merger_control, check_real_estate):
        flags += check(room)
    order = {WARNUNG: 0, HINWEIS: 1, OK: 2}
    return sorted(flags, key=lambda f: order[f.level])


# --- Gesetzliche Sätze in Aussagen ---------------------------------------------------

@dataclass(frozen=True)
class _Rate:
    subject: re.Pattern
    qualifier: re.Pattern | None
    periods: tuple[tuple[int, int, tuple[str, ...]], ...]  # (von Jahr, bis Jahr, gültige Sätze)
    law: str


_ANY = re.compile(r"")
RATES = [
    _Rate(re.compile(r"\bmwst|mehrwertsteuer|\btva\b|\biva\b", re.I), re.compile(r"reduziert|lebensmittel|medikament|bücher|taux réduit|aliquota ridotta", re.I),
          ((2011, 2017, ("2.5",)), (2018, 2023, ("2.5",)), (2024, 2100, ("2.6",))), "Art. 25 Abs. 2 MWSTG (reduzierter Satz)"),
    _Rate(re.compile(r"\bmwst|mehrwertsteuer|\btva\b|\biva\b", re.I), re.compile(r"beherbergung|hotellerie|übernachtung|hébergement|alloggio", re.I),
          ((2011, 2017, ("3.8",)), (2018, 2023, ("3.7",)), (2024, 2100, ("3.8",))), "Art. 25 Abs. 4 MWSTG (Sondersatz Beherbergung)"),
    _Rate(re.compile(r"\bmwst|mehrwertsteuer|\btva\b|\biva\b", re.I), _ANY,
          ((2011, 2017, ("8", "8.0")), (2018, 2023, ("7.7",)), (2024, 2100, ("8.1",))), "Art. 25 Abs. 1 MWSTG (Normalsatz)"),
    _Rate(re.compile(r"verrechnungssteuer|impôt anticipé|imposta preventiva", re.I), _ANY, ((1900, 2100, ("35",)),), "Art. 13 Abs. 1 lit. a VStG"),
    _Rate(re.compile(r"emissionsabgabe|droit de timbre d'émission|tassa d'emissione", re.I), _ANY, ((1900, 2100, ("1",)),), "Art. 8 Abs. 1 StG"),
    _Rate(re.compile(r"\bahv\b|ahv/iv/eo|\bavs\b", re.I), re.compile(r"ahv/iv/eo|ahv, iv und eo|gesamt|avs/ai/apg|avs/ai/ipg", re.I),
          ((2021, 2100, ("10.6",)),), "AHVG, IVG, EOG (Beitragssätze seit 2021)"),
    _Rate(re.compile(r"umwandlungssatz|taux de conversion|aliquota di conversione", re.I), _ANY, ((2014, 2100, ("6.8",)),), "Art. 14 Abs. 2 BVG (Mindestumwandlungssatz)"),
    _Rate(re.compile(r"bundessteuer|impôt fédéral direct|imposta federale diretta", re.I), re.compile(r"gewinn|bénéfice|utile", re.I),
          ((1998, 2100, ("8.5",)),), "Art. 68 DBG"),
]


def _rate_for(text: str) -> _Rate | None:
    for r in RATES:
        if r.subject.search(text) and (r.qualifier is _ANY or r.qualifier.search(text)):
            return r
    return None


def apply_rates(findings: list[Finding], today: dt.date | None = None) -> None:
    """Prozentsätze, die das Gesetz festlegt, gegen das Gesetz prüfen statt gegen den Datenraum."""
    year_now = (today or dt.date.today()).year
    for f in findings:
        if f.status in (Status.ABWEICHUNG, Status.QUELLE_FEHLT, Status.WIDERSPRUCH):
            continue
        text = f.claim.clean_text
        rate = _rate_for(text)
        percents = [x for x in f.claim.facts if x.kind == PERCENT]
        if not rate or len(percents) != 1 or len(f.claim.facts) != 1:
            continue
        years = [y for y in years_in(text) if 1990 <= y <= 2100]
        year = years[-1] if years else year_now
        valid = next((v for a, b, v in rate.periods if a <= year <= b), None)
        if valid is None:
            continue
        stated = percents[0].value
        ok = any(stated == Decimal(v) for v in valid)
        when = f" {year}" if years else f" (Stand {year})"
        if ok:
            if f.status in (Status.OHNE_BELEG, Status.UNGEPRUEFT) or not f.claim.citations:
                f.status = Status.GEPRUEFT
                f.reasons = [f"{format_value(PERCENT, stated)} entspricht dem gesetzlichen Satz{when}: {rate.law}."]
                f.method = "Schweizer Recht"
        else:
            f.status = Status.ABWEICHUNG
            f.method = "Schweizer Recht"
            f.reasons = [f"Der gesetzliche Satz{when} ist {' bzw. '.join(v + ' %' for v in valid)}, nicht "
                         f"{format_value(PERCENT, stated)} ({rate.law})."] + [r for r in f.reasons if "Keine Fundstelle" not in r]

