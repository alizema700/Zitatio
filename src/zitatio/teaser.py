"""Teaser für die Verkäuferseite: anonymes Kurzprofil aus dem Datenraum, jede Zahl mit Fundstelle.

Bei Nachfolgen und kleinen Verkäufen schreibt der Berater den Teaser von Hand und tippt die Zahlen ab. Zitatio
liest sie aus Jahresrechnungen, Handelsregister und Anhang, rundet sie für die Anonymität und gibt zwei Fassungen:
eine Prüffassung mit Fundstelle zu jeder Zahl (für Verkäufer und Berater) und eine Käuferfassung ohne Fundstellen.
Firma, Sitz und Personennamen kommen in der Käuferfassung nicht vor; Zitatio prüft das am Schluss selbst.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .dataroom import DataRoom
from .swiss import _fte, _register_doc, company_name, signatories
from .tables import doc_cells, years_in
from .verify import Evidence, _evidence

# Grossregionen des Bundesamts für Statistik
_REGIONS = {
    "Genferseeregion": ("VD", "VS", "GE"), "Espace Mittelland": ("BE", "FR", "SO", "NE", "JU"),
    "Nordwestschweiz": ("BS", "BL", "AG"), "Zürich": ("ZH",), "Ostschweiz": ("GL", "SH", "AR", "AI", "SG", "GR", "TG"),
    "Zentralschweiz": ("LU", "UR", "SZ", "OW", "NW", "ZG"), "Tessin": ("TI",),
}
_ROWS = {"umsatz": r"^(?:nettoerl[öo]s|umsatz|chiffre d'affaires|ricavi)", "ebitda": r"^ebitda",
         "gewinn": r"^(?:jahresgewinn|jahresverlust|jahresergebnis|reingewinn|bénéfice de l'exercice|perte de l'exercice"
                   r"|utile d'esercizio)",
         "eigenkapital": r"^(?:total\s+)?(?:eigenkapital|fonds propres|capitale proprio)",
         "bilanzsumme": r"^(?:bilanzsumme|total aktiven|total passiven)",
         "schulden": r"^(?:verzinsliche verbindlichkeiten|bankverbindlichkeiten|finanzverbindlichkeiten)",
         "liquiditaet": r"^flüssige mittel|^liquidités|^liquidità"}


# Managementsysteme, für die es Zertifikate gibt; ISO 20022 (Zahlungsverkehr), 8601 oder 4217 sind Formate
_CERTIFIABLE = {"9001", "13485", "14001", "45001", "27001", "50001", "22000", "17025", "15189", "22301"}
_CERTIFIED = re.compile(r"zertifi|certifi|zertifikat", re.I)


@dataclass
class Line:
    section: str
    label: str
    value: str
    evidence: list[Evidence]


def _figures(room: DataRoom) -> dict[int, dict[str, tuple[Decimal, Evidence]]]:
    out: dict[int, dict] = {}
    for doc in room.documents:
        if not doc.index or not re.search(r"jahresrechnung|jahresabschluss|comptes annuels|conto annuale", doc.title, re.I):
            continue
        years = years_in(doc.title)
        if len(years) != 1:
            continue
        values = out.setdefault(years[0], {})
        for p in range(1, len(doc.pages) + 1):
            for cell in doc_cells(doc, p):
                if cell.year not in (None, years[0]) or cell.plan:
                    continue
                for key, rx in _ROWS.items():
                    if key not in values and re.search(rx, cell.label, re.I):
                        before = doc.pages[p - 1][max(0, cell.fact.start - 2) : cell.fact.start]
                        sign = -1 if re.search(r"[-−(]\s?$", before) else 1  # Verlust: -350'000 oder (350'000)
                        values[key] = (sign * cell.fact.value[1], _evidence(doc, p, cell.fact.start, cell.fact.end))
    return {y: v for y, v in out.items() if "umsatz" in v}


def _mio(x: Decimal) -> str:
    return f"CHF {x / 1_000_000:.1f} Mio."


def codename(room: DataRoom) -> str:
    for doc in room.documents:
        m = re.search(r"\bProjekt\s+([A-ZÄÖÜ][\wäöü-]+)", doc.title + "\n" + "\n".join(doc.pages[:1]))
        if m:
            return f"Projekt {m.group(1)}"
    return "Projekt Alpha"


def teaser(room: DataRoom) -> list[Line]:
    lines: list[Line] = []
    reg = _register_doc(room)
    has = lambda label: any(line.label == label for line in lines)  # noqa: E731  ein Eintrag je Angabe
    if reg:
        for p, page in enumerate(reg.pages, 1):
            seat = re.search(r"Sitz:\s*[^\n]*?\b([A-Z]{2})\b", page)
            if seat and not has("Region"):
                region = next((r for r, cantons in _REGIONS.items() if seat.group(1) in cantons), None)
                if region:
                    lines.append(Line("Profil", "Region", region, [_evidence(reg, p, seat.start(1), seat.end(1))]))
            founded = re.search(r"Eintragung im Handelsregister:\s*\d{1,2}\.\d{1,2}\.(\d{4})", page)
            if founded and not has("Gegründet"):
                lines.append(Line("Profil", "Gegründet", f"{founded.group(1)[:3]}0er-Jahre",  # Jahrzehnt, nicht Jahr
                                  [_evidence(reg, p, founded.start(1), founded.end(1))]))
            form = re.search(r"Firma:\s*[^\n]*\b(AG|GmbH|SA|Sàrl|Sagl)\b", page)
            if form and not has("Rechtsform"):
                lines.append(Line("Profil", "Rechtsform", {"AG": "Aktiengesellschaft", "SA": "Aktiengesellschaft",
                                                           "GmbH": "GmbH", "Sàrl": "GmbH", "Sagl": "GmbH"}[form.group(1)],
                                  [_evidence(reg, p, form.start(1), form.end(1))]))
    certs: dict[str, Evidence] = {}
    for doc in room.documents:
        if not doc.index:
            continue
        for p, page in enumerate(doc.pages, 1):
            for m in re.finditer(r"\bISO[- ]?(\d{4,5})\b", page):
                start, end = page.rfind(".", 0, m.start()) + 1, page.find(".", m.end())
                sentence = page[start : end if end != -1 else len(page)]
                if m.group(1) in _CERTIFIABLE and (_CERTIFIED.search(sentence) or _CERTIFIED.search(doc.title)) \
                        and not re.search(r"\bzu zertifizieren|\bmuss[^.]{0,40}zertifiz|shall be certified", sentence, re.I):
                    certs.setdefault(f"ISO {m.group(1)}", _evidence(doc, p, m.start(), m.end()))
    if certs:
        lines.append(Line("Profil", "Zertifizierungen", ", ".join(sorted(certs)), list(certs.values())))

    figures = _figures(room)
    years = sorted(figures)[-3:]
    for y in years:
        v = figures[y]
        parts, ev = [f"Umsatz {_mio(v['umsatz'][0])}"], [v["umsatz"][1]]
        if "ebitda" in v:
            margin = f" ({v['ebitda'][0] / v['umsatz'][0] * 100:.0f} % Marge)" if v["umsatz"][0] > 0 else ""
            parts.append(f"EBITDA {_mio(v['ebitda'][0])}{margin}")
            ev.append(v["ebitda"][1])
        if "gewinn" in v:
            parts.append(f"{'Jahresgewinn' if v['gewinn'][0] >= 0 else 'Jahresverlust'} {_mio(abs(v['gewinn'][0]))}")
            ev.append(v["gewinn"][1])
        lines.append(Line("Finanzen", f"Geschäftsjahr {y}", ", ".join(parts), ev))
    first, last = (figures[years[0]]["umsatz"], figures[years[-1]]["umsatz"]) if years else (None, None)
    if len(years) >= 2 and first[0] > 0 and last[0] > 0:
        n = years[-1] - years[0]
        cagr = ((last[0] / first[0]) ** (Decimal(1) / n) - 1) * 100
        lines.append(Line("Finanzen", f"Umsatzwachstum {years[0]}–{years[-1]}", f"{cagr:.0f} % pro Jahr",
                          [first[1], last[1]]))
    if years:
        v = figures[years[-1]]
        if "eigenkapital" in v and "bilanzsumme" in v and v["bilanzsumme"][0] > 0:
            ratio = v["eigenkapital"][0] / v["bilanzsumme"][0] * 100
            lines.append(Line("Finanzen", f"Eigenkapitalquote {years[-1]}", f"{ratio:.0f} %",
                              [v["eigenkapital"][1], v["bilanzsumme"][1]]))
        if "schulden" in v and "liquiditaet" in v:
            net = v["schulden"][0] - v["liquiditaet"][0]
            label = "Nettoverschuldung" if net > 0 else "Nettoliquidität"
            lines.append(Line("Finanzen", f"{label} {years[-1]}", _mio(abs(net)),
                              [v["schulden"][1], v["liquiditaet"][1]]))
        fte = _fte(room, years[-1])
        if fte:
            count, doc, p = fte
            rounded = int(round(count, -1)) if count >= 30 else count
            m = re.search(rf"\b{count}\b", doc.pages[p - 1])
            lines.append(Line("Profil", "Mitarbeitende", f"rund {rounded} Vollzeitstellen",
                              [_evidence(doc, p, m.start(), m.end())] if m else []))
    order = {"Profil": 0, "Finanzen": 1}
    return sorted(lines, key=lambda line: order[line.section])


def _forbidden(room: DataRoom) -> set[str]:
    """Wörter, die die Gesellschaft verraten: Firma, Sitz, Namen der Zeichnungsberechtigten."""
    words = set()
    name = company_name(room)
    if name:
        words |= {w for w in re.findall(r"[\wäöüÄÖÜ]{4,}", name)}
    reg = _register_doc(room)
    if reg:
        seat = re.search(r"Sitz:\s*([^\n]+)", "\n".join(reg.pages))
        if seat:
            words |= {w for w in re.findall(r"[\wäöüÄÖÜ]{4,}", seat.group(1))}
    for s in signatories(room):
        words |= {w for w in re.findall(r"[\wäöüÄÖÜ]{4,}", s.name)}
    regions = {w.lower() for r in _REGIONS for w in re.findall(r"[\wäöüÄÖÜ]{4,}", r)}  # "Zürich" ist auch die Region
    return {w.lower() for w in words} - {"medtech", "holding", "gruppe", "group"} - regions


def anonymity_leaks(text: str, room: DataRoom) -> list[str]:
    tokens = {t.lower() for t in re.findall(r"[\wäöüÄÖÜ]{4,}", text)}
    return sorted(tokens & _forbidden(room))


def to_markdown(lines: list[Line], name: str, with_sources: bool) -> str:
    out = [f"# {name}: Kurzprofil", ""]
    out.append("_Prüffassung mit Fundstellen, nur für Verkäufer und Berater._" if with_sources else
               "_Vertraulich. Weitere Informationen nach Unterzeichnung einer Geheimhaltungsvereinbarung._")
    for section in ("Profil", "Finanzen"):
        items = [line for line in lines if line.section == section]
        if not items:
            continue
        out += ["", f"## {section}", ""]
        if with_sources:
            out += ["| Angabe | Wert | Fundstelle |", "|---|---|---|"]
            out += [f"| {i.label} | {i.value} | " + "; ".join(dict.fromkeys(f"{e.doc_label}, S. {e.page}" for e in i.evidence)) + " |"
                    for i in items]
        else:
            out += [f"- **{i.label}:** {i.value}" for i in items]
    if with_sources:
        out += ["", "Zahlen gerundet. Vor dem Versand prüfen, ob Region, Zertifizierungen oder Zahlen zusammen auf die "
                "Gesellschaft schliessen lassen."]
    return "\n".join(out) + "\n"
