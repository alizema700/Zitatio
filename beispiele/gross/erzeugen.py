"""Grosser, realistischer Testfall: fiktiver Datenraum mit über 250 Seiten und ein DD-Bericht
mit über 200 Aussagen, von denen nur 14 absichtlich falsch sind. Dazu drei Widersprüche
im Datenraum selbst, wie sie bei falschen Angaben des Verkäufers vorkommen.

Alle Firmen, Personen und Zahlen sind erfunden. Der Zufall ist fest (SEED), damit der Test
reproduzierbar bleibt.

Aufruf: python beispiele/gross/erzeugen.py   (braucht fpdf2 und openpyxl)
Erzeugt datenraum/, dd-bericht.md, wahrheit.json (welche Aussage richtig ist und welche nicht)
und widersprueche.json (welche Grössen im Datenraum absichtlich widersprüchlich sind).
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF

HERE = Path(__file__).parent
OUT = HERE / "datenraum"
SEED = 7
rng = random.Random(SEED)

MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
          "Oktober", "November", "Dezember"]


# --- Formatierung -------------------------------------------------------------

def chf(n: int) -> str:
    return f"{n:,}".replace(",", "'")


def mio(n: int, digits: int = 2) -> str:
    return f"{n / 1_000_000:.{digits}f}"


def d(date: dt.date) -> str:
    return date.strftime("%d.%m.%Y")


def d_long(date: dt.date) -> str:
    return f"{date.day}. {MONTHS[date.month - 1]} {date.year}"


def uid_with_check(eight: str) -> str:
    weights = (5, 4, 3, 2, 7, 6, 5, 4)
    check = 11 - sum(int(c) * w for c, w in zip(eight, weights)) % 11
    check = 0 if check == 11 else check
    if check == 10:
        return ""
    digits = eight + str(check)
    return f"CHE-{digits[:3]}.{digits[3:6]}.{digits[6:]}"


# --- Datenraum-Modell -----------------------------------------------------------

@dataclass
class Doc:
    index: str
    title: str
    pages: list[list[str]]
    kind: str = "pdf"
    sheets: list = field(default_factory=list)  # nur Excel: (Name, Zeilen)


@dataclass
class Statement:
    section: str
    text: str  # mit Fundstelle
    correct: bool = True
    error: str | None = None  # Fehlerart, wenn absichtlich falsch
    detectable: bool = True  # kann eine reine Regelprüfung den Fehler sehen?
    note: str = ""  # z. B. "abgeleitet" für berechnete Werte


DOCS: list[Doc] = []
REPORT: list[Statement] = []
CONFLICTS: list[dict] = []  # absichtlich eingebaute Widersprüche im Datenraum

FILLER = [
    "Die Parteien verpflichten sich, die gegenseitigen Pflichten nach Treu und Glauben zu erfüllen.",
    "Änderungen und Ergänzungen dieses Vertrags bedürfen zu ihrer Gültigkeit der Schriftform.",
    "Sollte eine Bestimmung dieses Vertrags unwirksam sein, so bleibt die Wirksamkeit der übrigen Bestimmungen unberührt.",
    "Die unwirksame Bestimmung ist durch eine wirksame zu ersetzen, die dem wirtschaftlichen Zweck möglichst nahekommt.",
    "Mitteilungen gelten als zugestellt, wenn sie an die zuletzt bekannt gegebene Adresse versandt wurden.",
    "Die Rechte und Pflichten aus diesem Vertrag dürfen nur mit vorgängiger schriftlicher Zustimmung abgetreten werden.",
    "Jede Partei trägt die ihr im Zusammenhang mit diesem Vertrag entstehenden Kosten selbst.",
    "Die Überschriften dienen nur der Übersicht und sind für die Auslegung ohne Bedeutung.",
    "Die Parteien behandeln alle vertraulichen Informationen mit der gebotenen Sorgfalt.",
    "Die Geheimhaltungspflicht gilt nicht für Informationen, die öffentlich bekannt sind oder werden.",
    "Die Lieferantin stellt sicher, dass ihre Unterlieferanten die gleichen Pflichten einhalten.",
    "Allfällige Mängel sind der anderen Partei unverzüglich nach ihrer Entdeckung schriftlich anzuzeigen.",
    "Die Parteien informieren sich gegenseitig über wesentliche Änderungen ihrer Organisation.",
    "Für die Dauer dieses Vertrags unterhalten die Parteien eine angemessene Betriebshaftpflichtversicherung.",
    "Die Kundin ist berechtigt, die Einhaltung der Qualitätsvorgaben nach vorgängiger Ankündigung zu prüfen.",
    "Die Lieferantin führt ein Qualitätsmanagementsystem nach den anerkannten Normen der Medizintechnik.",
    "Die Bearbeitung von Personendaten erfolgt nach den Vorgaben des Datenschutzgesetzes.",
    "Die Parteien bemühen sich, Streitigkeiten zunächst einvernehmlich beizulegen.",
    "Der Verwaltungsrat nimmt vom Bericht der Geschäftsleitung Kenntnis und genehmigt ihn.",
    "Die Geschäftsleitung erläutert den Geschäftsgang und beantwortet die Fragen der Mitglieder.",
    "Der Verwaltungsrat beschliesst einstimmig, die Angelegenheit an der nächsten Sitzung erneut zu behandeln.",
    "Die Rechnungslegung erfolgt nach den Bestimmungen des schweizerischen Obligationenrechts.",
    "Die Bewertung erfolgt grundsätzlich zu Anschaffungs- oder Herstellungskosten abzüglich notwendiger Wertberichtigungen.",
    "Die Gesellschaft beschäftigt Mitarbeitende in den Bereichen Entwicklung, Produktion und Vertrieb.",
    "Die Angaben beruhen auf den Unterlagen, die der Revisionsstelle zur Verfügung gestellt wurden.",
    "Die Arbeitnehmerin verpflichtet sich, ihre ganze Arbeitskraft der Gesellschaft zu widmen.",
    "Nebenbeschäftigungen bedürfen der vorgängigen Zustimmung des Verwaltungsrats.",
    "Das Arbeitsverhältnis untersteht im Übrigen den Bestimmungen des Obligationenrechts.",
    "Die Versicherung deckt Schäden gemäss den Allgemeinen Versicherungsbedingungen.",
    "Die Mieterin hat die Mietsache sorgfältig zu gebrauchen und auf die Hausbewohner Rücksicht zu nehmen.",
    "Bauliche Änderungen durch die Mieterin bedürfen der schriftlichen Zustimmung der Vermieterin.",
    "Die Nebenkosten werden nach dem effektiven Aufwand jährlich abgerechnet.",
    "Die Lizenznehmerin darf die Software ausschliesslich für eigene Zwecke verwenden.",
    "Die Darlehensnehmerin informiert die Bank unverzüglich über wesentliche nachteilige Veränderungen.",
    "Die Bank kann jederzeit Auskünfte über die finanzielle Lage der Darlehensnehmerin verlangen.",
]
NOISE = [
    lambda: f"Die Bearbeitungsgebühr für Änderungen beträgt CHF {rng.choice([150, 200, 250, 300, 450])}.",
    lambda: f"Die Ausfertigung erfolgte in {rng.choice(['zwei', 'drei'])} Exemplaren.",
    lambda: f"Referenz: Dossier {rng.randint(1000, 9999)}-{rng.randint(10, 99)}.",
    lambda: f"Stand der Unterlagen: {d(dt.date(2026, rng.randint(1, 8), rng.randint(1, 28)))}.",
    lambda: f"Die Verzugszinsen betragen {rng.choice(['5', '5.0'])} % pro Jahr.",
]


def filler(n: int) -> list[str]:
    out = []
    for _ in range(n):
        out.append(rng.choice(NOISE)() if rng.random() < 0.18 else rng.choice(FILLER))
    return out


def page(*facts: str, fill: int = 9, title: str | None = None) -> list[str]:
    """Eine Seite: wenige Kernaussagen, verteilt zwischen Fülltext."""
    body = filler(fill)
    for fact in facts:
        body.insert(rng.randint(0, len(body)), fact)
    return ([title] if title else []) + body


def say(section: str, text: str, **kw) -> None:
    REPORT.append(Statement(section, text, **kw))


def cite(index: str, page_no: int) -> str:
    return f"[DR {index}, S. {page_no}]"


# --- Gesellschaft ---------------------------------------------------------------

UID = ""
while not UID:
    UID = uid_with_check("".join(str(rng.randint(0, 9)) for _ in range(8)))
NAME = "Rheintal Medtech AG"
SEC = "1. Gesellschaft und Organisation"


def build_corporate() -> None:
    founded = dt.date(2004, 5, 17)
    capital = 1_200_000
    shares = 12_000
    DOCS.append(Doc("1.1", "Handelsregisterauszug", [
        page(f"Firma: {NAME}", f"UID: {UID}", "Sitz: Altstätten SG",
             f"Eintragung im Handelsregister: {d(founded)}",
             f"Aktienkapital: CHF {chf(capital)}, eingeteilt in {chf(shares)} Namenaktien zu CHF 100, vollständig liberiert.",
             fill=4, title="Handelsregister des Kantons St. Gallen - Auszug (fiktiv)"),
        page("Verwaltungsrat: Dr. Beatrice Rohner, Präsidentin; Luca Fässler, Mitglied; Sandra Oberholzer, Mitglied.",
             "Revisionsstelle: Treuhand Rheineck AG, Rheineck.", fill=5),
    ]))
    say(SEC, f"Die {NAME} (UID {UID}) hat ihren Sitz in Altstätten SG {cite('1.1', 1)}.")
    say(SEC, f"Die Gesellschaft ist seit dem {d_long(founded)} im Handelsregister eingetragen {cite('1.1', 1)}.")
    say(SEC, f"Das Aktienkapital von CHF {mio(capital, 1)} Mio. ist voll liberiert {cite('1.1', 1)}.")
    say(SEC, f"Der Verwaltungsrat besteht aus drei Mitgliedern unter dem Präsidium von Dr. Beatrice Rohner {cite('1.1', 2)}.")
    say(SEC, f"Als Revisionsstelle amtet die Treuhand Rheineck AG {cite('1.1', 2)}.")

    statuten = [page(fill=10, title="Statuten der Rheintal Medtech AG") for _ in range(8)]
    statuten[1] = page("Art. 5: Die Übertragung von Namenaktien bedarf der Zustimmung des Verwaltungsrats (Vinkulierung).", fill=9)
    statuten[3] = page("Art. 12: Die Generalversammlung wird spätestens 20 Tage vor dem Versammlungstag einberufen.", fill=9)
    statuten[5] = page("Art. 21: Der Verwaltungsrat besteht aus einem oder mehreren Mitgliedern mit einer Amtsdauer von drei Jahren.", fill=9)
    # Widerspruch: Die Statuten wurden nach der Kapitalerhöhung nicht nachgeführt.
    statuten[0].insert(1, "Art. 3: Das Aktienkapital beträgt CHF 1'000'000 und ist eingeteilt in 10'000 Namenaktien zu CHF 100.")
    CONFLICTS.append({"groesse": "Aktienkapital", "dokumente": ["1.1", "1.2"]})
    DOCS.append(Doc("1.2", "Statuten", statuten))
    say(SEC, f"Die Namenaktien sind vinkuliert; jede Übertragung braucht die Zustimmung des Verwaltungsrats {cite('1.2', 2)}.")
    say(SEC, f"Die Generalversammlung ist mindestens 20 Tage im Voraus einzuberufen {cite('1.2', 4)}.")
    say(SEC, f"Die Amtsdauer der Verwaltungsräte beträgt drei Jahre {cite('1.2', 6)}.")
    say(SEC, f"Die Statuten enthalten keine Opting-out- oder Opting-up-Klausel {cite('1.2', 7)}.")

    holders = [("Rohner Beteiligungen AG", 7_200), ("Luca Fässler", 2_400), ("Sandra Oberholzer", 1_200),
               ("Mitarbeiterbeteiligung Rheintal GmbH", 1_200)]
    DOCS.append(Doc("1.3", "Aktienbuch", [
        page(*[f"{h}: {chf(n)} Namenaktien ({n / shares * 100:.0f} %)" for h, n in holders], fill=3,
             title="Aktienbuch per 31.12.2025"),
        page(fill=8), page(fill=8),
    ]))
    say(SEC, f"Die Rohner Beteiligungen AG hält 7'200 Namenaktien und damit 60 % des Kapitals {cite('1.3', 1)}.")
    say(SEC, f"Über die Mitarbeiterbeteiligung Rheintal GmbH sind 10 % der Aktien im Besitz von Mitarbeitenden {cite('1.3', 1)}.")

    protocols = []
    for i in range(10):
        date = dt.date(2025, 1 + i, 14 + (i % 3))
        facts = [f"Sitzung des Verwaltungsrats vom {d(date)}"]
        if i == 2:
            facts.append("Der Verwaltungsrat genehmigt die Investition in eine zweite Spritzgusslinie über CHF 2'350'000.")
        if i == 6:
            facts.append("Der Verwaltungsrat beschliesst, den Verkaufsprozess mit einem M&A-Berater vorzubereiten.")
        if i == 8:
            facts.append("Der Verwaltungsrat nimmt Kenntnis vom Rechtsstreit mit der Nordlicht Medical GmbH.")
        protocols.append(page(*facts, fill=8, title="Protokoll (fiktiv)"))
    DOCS.append(Doc("1.4", "Protokolle Verwaltungsrat 2025", protocols))
    say(SEC, f"Am 16. März 2025 genehmigte der Verwaltungsrat eine zweite Spritzgusslinie für CHF 2.35 Mio. {cite('1.4', 3)}.")
    say(SEC, f"Der Verkaufsprozess wurde vom Verwaltungsrat an der Sitzung vom 14.07.2025 angestossen {cite('1.4', 7)}.")
    say(SEC, f"Die Protokolle des Verwaltungsrats sind lückenlos vorhanden und unterzeichnet {cite('1.4', 1)}.")


# --- Finanzen -------------------------------------------------------------------

FIN = "2. Finanzen"
YEARS = {2023: 27_940_221, 2024: 29_540_118, 2025: 31_862_415}


def income_statement(year: int) -> dict[str, int]:
    revenue = YEARS[year]
    material = int(revenue * rng.uniform(0.33, 0.36))
    personnel = int(revenue * rng.uniform(0.37, 0.39))
    other = int(revenue * rng.uniform(0.11, 0.12))
    ebitda = revenue - material - personnel - other
    depreciation = int(revenue * 0.045)
    ebit = ebitda - depreciation
    interest = 187_400 if year == 2025 else 201_300
    taxes = int((ebit - interest) * 0.17)
    return {"Nettoerlöse aus Lieferungen und Leistungen": revenue, "Materialaufwand": material,
            "Personalaufwand": personnel, "Übriger betrieblicher Aufwand": other, "EBITDA": ebitda,
            "Abschreibungen": depreciation, "Betriebsergebnis (EBIT)": ebit, "Finanzaufwand": interest,
            "Steuern": taxes, "Jahresgewinn": ebit - interest - taxes}


IS = {y: income_statement(y) for y in YEARS}


def build_financials() -> None:
    for n, year in enumerate(YEARS, start=1):
        cur, prev = IS[year], IS.get(year - 1)
        prev = dict(prev) if prev else None
        if year == 2025:
            # Widerspruch: Die Vorjahresspalte weicht ohne Erläuterung von der Jahresrechnung 2024 ab.
            prev["Personalaufwand"] += 142_000
            CONFLICTS.append({"groesse": "Personalaufwand 2024", "dokumente": ["2.2", "2.3"]})
        rows = [f"{k} {chf(v)}" + (f" {chf(prev[k])}" if prev else "") for k, v in cur.items()]
        cash = rng.randint(2_100_000, 3_900_000)
        debt = 6_400_000 if year == 2025 else 7_100_000
        balance = [f"Flüssige Mittel {chf(cash)}", f"Forderungen aus Lieferungen und Leistungen {chf(int(YEARS[year] * 0.16))}",
                   f"Vorräte {chf(int(YEARS[year] * 0.12))}", f"Sachanlagen {chf(int(YEARS[year] * 0.31))}",
                   f"Verzinsliche Verbindlichkeiten {chf(debt)}", f"Eigenkapital {chf(int(YEARS[year] * 0.41))}"]
        pages = [
            page(fill=6, title=f"{NAME} - Jahresrechnung {year} (fiktiv)"),
            page(fill=7, title="Inhaltsverzeichnis und Grundlagen"),
            ["Erfolgsrechnung " + str(year) + (" und " + str(year - 1) if prev else "") + " (in CHF)"] + rows,
            ["Bilanz per 31.12." + str(year) + " (in CHF)"] + balance,
            page(fill=9, title="Anhang zur Jahresrechnung"),
            page(f"Die Gesellschaft beschäftigte im Jahresdurchschnitt {150 + 8 * n} Vollzeitstellen.", fill=8),
            page(f"Verpflichtungen aus langfristigen Mietverträgen: CHF {chf(4_380_000 - 300_000 * n)}.", fill=8),
            page(f"Verbindlichkeiten gegenüber Vorsorgeeinrichtungen: CHF {chf(84_000 + 6_000 * n)}.", fill=8),
        ]
        if year == 2025:
            pages.insert(6, page("Ereignisse nach dem Bilanzstichtag: Keine, die eine Anpassung erfordern.", fill=8))
            pages.insert(2, page(fill=8, title="Lagebericht"))
        DOCS.append(Doc(f"2.{n}", f"Jahresrechnung {year}", pages))

    jr25 = "2.3"
    er_page = 4  # Erfolgsrechnung 2025 (nach Lagebericht)
    say(FIN, f"Der Nettoerlös 2025 beträgt CHF {mio(IS[2025]['Nettoerlöse aus Lieferungen und Leistungen'])} Mio. {cite(jr25, er_page)}.")
    say(FIN, f"Im Vorjahr lag der Nettoerlös bei CHF {mio(IS[2024]['Nettoerlöse aus Lieferungen und Leistungen'])} Mio. {cite('2.2', 3)}.")
    say(FIN, f"2023 erzielte die Gesellschaft einen Nettoerlös von CHF {chf(IS[2023]['Nettoerlöse aus Lieferungen und Leistungen'])} {cite('2.1', 3)}.")
    growth = (YEARS[2025] / YEARS[2024] - 1) * 100
    say(FIN, f"Das entspricht einem Wachstum von {growth:.1f} % gegenüber dem Vorjahr {cite(jr25, er_page)}.",
        note="abgeleitet")
    say(FIN, f"Der Materialaufwand 2025 belief sich auf CHF {mio(IS[2025]['Materialaufwand'])} Mio. {cite(jr25, er_page)}.")
    say(FIN, f"Der Personalaufwand stieg auf CHF {mio(IS[2025]['Personalaufwand'])} Mio. {cite(jr25, er_page)}.")
    say(FIN, f"Das EBITDA 2025 beträgt CHF {mio(IS[2025]['EBITDA'])} Mio. {cite(jr25, er_page)}.")
    margin = IS[2025]["EBITDA"] / YEARS[2025] * 100
    say(FIN, f"Die EBITDA-Marge liegt damit bei {margin:.1f} % {cite(jr25, er_page)}.", note="abgeleitet")
    say(FIN, f"Die Abschreibungen betragen CHF {chf(IS[2025]['Abschreibungen'])} {cite(jr25, er_page)}.")
    say(FIN, f"Der Jahresgewinn 2025 beläuft sich auf CHF {mio(IS[2025]['Jahresgewinn'])} Mio. {cite(jr25, er_page)}.")
    say(FIN, f"Der Finanzaufwand sank auf CHF {chf(IS[2025]['Finanzaufwand'])} {cite(jr25, er_page)}.")
    say(FIN, f"Das EBITDA 2024 betrug CHF {mio(IS[2024]['EBITDA'])} Mio. {cite('2.2', 3)}.")
    say(FIN, f"Das EBITDA 2023 betrug CHF {mio(IS[2023]['EBITDA'])} Mio. {cite('2.1', 3)}.")
    say(FIN, f"Die verzinslichen Verbindlichkeiten per 31.12.2025 betragen CHF 6.4 Mio. {cite(jr25, er_page + 1)}.")
    say(FIN, f"Die Gesellschaft beschäftigte 2025 durchschnittlich 174 Vollzeitstellen {cite(jr25, 7)}.")
    say(FIN, f"Die langfristigen Mietverpflichtungen belaufen sich auf CHF 3.48 Mio. {cite(jr25, 9)}.")
    say(FIN, f"Gegenüber Vorsorgeeinrichtungen bestehen Verbindlichkeiten von CHF 102'000 {cite(jr25, 10)}.")
    say(FIN, f"Wesentliche Ereignisse nach dem Bilanzstichtag gab es keine {cite(jr25, 8)}.")
    say(FIN, f"Die Jahresrechnung wurde nach den Bestimmungen des Obligationenrechts erstellt {cite(jr25, 6)}.")
    say(FIN, f"Die Jahresrechnungen 2023 bis 2025 liegen vollständig vor {cite('2.1', 1)}.")

    DOCS.append(Doc("2.4", "Revisionsbericht 2025", [
        page("Nach unserer Beurteilung entspricht die Jahresrechnung für das am 31.12.2025 abgeschlossene Geschäftsjahr dem schweizerischen Gesetz und den Statuten.",
             fill=7, title="Bericht der Revisionsstelle zur eingeschränkten Revision (fiktiv)"),
        page("Wir sind auf keine Sachverhalte gestossen, aus denen wir schliessen müssten, dass die Jahresrechnung nicht Gesetz und Statuten entspricht.", fill=8),
        page("Treuhand Rheineck AG, Rheineck, 18.03.2026", fill=6),
    ]))
    say(FIN, f"Die Revisionsstelle hat die Jahresrechnung 2025 ohne Einschränkung bestätigt {cite('2.4', 1)}.")
    say(FIN, f"Der Revisionsbericht datiert vom 18.03.2026 {cite('2.4', 3)}.")

    # Management Accounts in Excel, Werte in TCHF
    monthly = []
    remaining = YEARS[2025]
    for m in range(12):
        share = remaining if m == 11 else int(YEARS[2025] * rng.uniform(0.074, 0.091))
        remaining -= share
        monthly.append(share)
    sheets = []
    for m, rev in enumerate(monthly):
        ebitda = int(rev * rng.uniform(0.12, 0.16))
        sheets.append((MONTHS[m][:3] + " 2025", [
            [f"Management Accounts {MONTHS[m]} 2025, in TCHF"],
            ["Umsatz", round(rev / 1000)], ["Bruttomarge", round(rev * 0.65 / 1000)],
            ["EBITDA", round(ebitda / 1000)], ["Auftragseingang", round(rev * rng.uniform(0.95, 1.12) / 1000)],
        ]))
    backlog = 14_820
    # Widerspruch: Die Übersicht der Management Accounts nennt einen anderen Jahresumsatz als der Abschluss.
    CONFLICTS.append({"groesse": "Umsatz 2025", "dokumente": ["2.3", "2.5"]})
    sheets.append(("Übersicht", [["Kennzahlen 2025, in TCHF"], ["Umsatz kumuliert", round(YEARS[2025] / 1000) + 455],
                                 ["Auftragsbestand 31.12.", backlog], ["Mitarbeitende (FTE)", "178"]]))
    DOCS.append(Doc("2.5", "Management Accounts 2025", [], kind="xlsx", sheets=sheets))
    MA = "2.5"
    say(FIN, f"Im Dezember 2025 erzielte die Gesellschaft einen Umsatz von CHF {mio(round(monthly[11] / 1000) * 1000)} Mio. {cite(MA, 12)}.")
    say(FIN, f"Der Juni war mit TCHF {chf(round(monthly[5] / 1000))} Umsatz ein durchschnittlicher Monat {cite(MA, 6)}.")
    say(FIN, f"Der Auftragsbestand per Ende 2025 beträgt CHF 14.8 Mio. {cite(MA, 13)}.")
    say(FIN, f"Das EBITDA im März 2025 betrug TCHF {chf(round(sheets[2][1][3][1]))} {cite(MA, 3)}.")
    say(FIN, f"Die Management Accounts werden monatlich erstellt und vom CFO freigegeben {cite(MA, 1)}.")

    budget = [("Budget 2026", [["Budget 2026, in TCHF"], ["Umsatz", 34_150], ["EBITDA", 4_980], ["Investitionen", 2_700]]),
              ("Annahmen", [["Annahmen Budget 2026"], ["Preiserhöhung", "2.5 %"], ["Neue Kunden", "3"]]),
              ("Personal", [["Personalplanung 2026"], ["FTE Ende 2026", "186"]])]
    DOCS.append(Doc("2.6", "Budget 2026", [], kind="xlsx", sheets=budget))
    say(FIN, f"Für 2026 budgetiert das Management einen Umsatz von CHF 34.15 Mio. {cite('2.6', 1)}.")
    say(FIN, f"Das budgetierte EBITDA 2026 beträgt CHF 4.98 Mio. {cite('2.6', 1)}.")
    say(FIN, f"Das Budget unterstellt eine Preiserhöhung von 2.5 % {cite('2.6', 2)}.")
    say(FIN, f"Die geplanten Investitionen 2026 belaufen sich auf CHF 2.7 Mio. {cite('2.6', 1)}.")
    say(FIN, f"Das Budget erscheint angesichts des Auftragsbestands plausibel {cite('2.6', 1)}.")


# --- Steuern --------------------------------------------------------------------

TAX = "3. Steuern"


def build_tax() -> None:
    for n, year in enumerate((2023, 2024), start=1):
        taxable = int((IS[year]["Betriebsergebnis (EBIT)"] - IS[year]["Finanzaufwand"]) * 0.98)
        DOCS.append(Doc(f"3.{n}", f"Veranlagungsverfügung {year}", [
            page(f"Steuerbarer Reingewinn {year}: CHF {chf(taxable)}", f"Veranlagung vom {d(dt.date(year + 1, 9, 12 + n))}",
                 fill=6, title=f"Kantonales Steueramt St. Gallen - Veranlagungsverfügung Staats- und Gemeindesteuern {year} (fiktiv)"),
            page("Die Veranlagung ist rechtskräftig.", fill=8),
            page(fill=8),
        ]))
        say(TAX, f"Für {year} wurde ein steuerbarer Reingewinn von CHF {chf(taxable)} veranlagt {cite(f'3.{n}', 1)}.")
        say(TAX, f"Die Veranlagung {year} ist rechtskräftig {cite(f'3.{n}', 2)}.")
    DOCS.append(Doc("3.3", "MWST-Abrechnungen 2025", [
        page(f"Quartal {q}: Umsatzsteuer CHF {chf(rng.randint(560_000, 690_000))}, Vorsteuer CHF {chf(rng.randint(310_000, 380_000))}",
             fill=7, title="Mehrwertsteuer-Abrechnung (fiktiv)") for q in range(1, 5)
    ]))
    say(TAX, f"Die MWST-Abrechnungen 2025 wurden für alle vier Quartale eingereicht {cite('3.3', 1)}.")
    say(TAX, f"Steuerliche Risiken aus offenen Veranlagungen bestehen für 2025, da diese noch nicht veranlagt ist {cite('3.2', 2)}.")


# --- Immobilien -----------------------------------------------------------------

RE = "4. Immobilien"
LEASES = [
    ("4.1.1", "Mietvertrag Produktion Altstätten", "Produktions- und Bürogebäude, Industriestrasse 14, Altstätten", 684_000, dt.date(2031, 12, 31), 12),
    ("4.1.2", "Mietvertrag Lager Heerbrugg", "Lagerhalle, Auerstrasse 3, Heerbrugg", 138_000, dt.date(2028, 6, 30), 6),
    ("4.1.3", "Mietvertrag Büro Zürich", "Büroflächen, Hardturmstrasse 161, Zürich", 96_000, dt.date(2027, 3, 31), 6),
]


def build_real_estate() -> None:
    for idx, title, obj, rent, end, notice in LEASES:
        start = dt.date(end.year - 10 if "Produktion" in title else end.year - 5, 1, 1)
        DOCS.append(Doc(idx, title, [
            page(f"Mietobjekt: {obj}", "Vermieterin: Rhein Immobilien AG (fiktiv)", fill=7, title=f"{title} (fiktiv)"),
            page(f"Das Mietverhältnis beginnt am {d(start)} und ist fest abgeschlossen bis {d(end)}.", fill=8),
            page(f"Der jährliche Nettomietzins beträgt CHF {chf(rent)}.", "Der Mietzins ist zu 100 % an den Landesindex der Konsumentenpreise gebunden.", fill=7),
            page(f"Nach Ablauf der festen Dauer kann das Mietverhältnis mit einer Frist von {notice} Monaten gekündigt werden.", fill=8),
            page("Die Mieterin hat ein einmaliges Optionsrecht auf Verlängerung um fünf Jahre.", fill=8),
            page("Unterschriften der Parteien", fill=5),
        ]))
    a, b, c = LEASES
    say(RE, f"Die Produktion ist in Altstätten eingemietet; der Vertrag ist fest bis {d_long(a[4])} {cite(a[0], 2)}.")
    say(RE, f"Der Nettomietzins für Altstätten beträgt CHF {chf(a[3])} pro Jahr {cite(a[0], 3)}.")
    say(RE, f"Danach ist der Vertrag mit zwölf Monaten Frist kündbar {cite(a[0], 4)}.")
    say(RE, f"Die Mieterin kann den Vertrag einmal um fünf Jahre verlängern {cite(a[0], 5)}.")
    say(RE, f"Das Lager in Heerbrugg kostet CHF {chf(b[3])} pro Jahr {cite(b[0], 3)}.")
    say(RE, f"Der Mietvertrag für das Lager läuft fest bis 30.06.2028 {cite(b[0], 2)}.")
    say(RE, f"Für das Lager gilt danach eine Kündigungsfrist von 6 Monaten {cite(b[0], 4)}.")
    say(RE, f"Das Büro in Zürich kostet jährlich CHF 96'000 {cite(c[0], 3)}.")
    say(RE, f"Der Büromietvertrag Zürich endet fest am 31.03.2027 {cite(c[0], 2)}.")
    say(RE, f"Alle Mietzinse sind vollständig an den Landesindex der Konsumentenpreise gebunden {cite(a[0], 3)}.")
    total = sum(x[3] for x in LEASES)
    say(RE, f"Insgesamt betragen die jährlichen Mietkosten CHF {chf(total)} {cite(a[0], 3)}.", note="abgeleitet")
    say(RE, f"Die Gesellschaft besitzt keine eigenen Liegenschaften {cite(a[0], 1)}.")


# --- Verträge -------------------------------------------------------------------

CON = "5. Wesentliche Verträge"
CUSTOMERS = [
    ("5.1", "Alpstein Kliniken AG", 6_420_000, True),
    ("5.2", "Medizentrum Thurgau AG", 3_870_000, False),
    ("5.3", "Helvetic Ortho GmbH", 2_960_000, True),
    ("5.4", "Lakeside Dental SA", 2_140_000, False),
    ("5.5", "Spitalverbund Ostschweiz (fiktiv)", 4_780_000, True),
    ("5.6", "Nordlicht Medical GmbH", 1_310_000, False),
    ("5.10", "Klinik Seeblick AG", 1_180_000, False),
    ("5.11", "OrthoCenter Chur AG", 960_000, True),
    ("5.12", "Praxisgruppe Linth AG", 740_000, False),
    ("5.13", "Bodensee Reha GmbH", 1_520_000, False),
    ("5.14", "Alpine Sports Clinic AG", 880_000, True),
    ("5.15", "Medisupply Liechtenstein AG", 1_090_000, False),
]
SUPPLIERS = [
    ("5.7", "Precitec Metall AG", "Titanrohlinge", 2_480_000),
    ("5.8", "Silikon Werke Rorschach AG", "medizinisches Silikon", 1_120_000),
    ("5.9", "Logistik Säntis AG", "Lager- und Transportleistungen", 640_000),
]
CUSTOMER_TERMS = {}


def build_contracts() -> None:
    for idx, name, volume, coc in CUSTOMERS:
        start = dt.date(rng.choice([2021, 2022, 2023]), rng.choice([1, 4, 7, 10]), 1)
        end = dt.date(start.year + rng.choice([5, 6, 7]), start.month, 1) - dt.timedelta(days=1)
        escalation = rng.choice(["1.5", "2.0", "2.25", "2.5"])
        notice = rng.choice([3, 6, 9])
        payment = rng.choice([30, 45, 60])
        cap = rng.choice([1_000_000, 2_000_000, 2_500_000, 5_000_000])
        CUSTOMER_TERMS[idx] = dict(start=start, end=end, escalation=escalation, notice=notice, payment=payment, cap=cap)
        coc_text = (f"Bei einem Kontrollwechsel bei der Lieferantin ist die Kundin berechtigt, diesen Vertrag mit einer Frist von drei Monaten zu kündigen."
                    if coc else "Ein Kontrollwechsel bei einer der Parteien berührt den Bestand dieses Vertrags nicht.")
        DOCS.append(Doc(idx, f"Liefervertrag {name}", [
            page(f"Liefervertrag zwischen {NAME} (Lieferantin) und {name} (Kundin) (fiktiv)", fill=7),
            page(f"Der Vertrag tritt am {d(start)} in Kraft und endet am {d(end)}.", fill=8),
            page(f"Das geschätzte jährliche Bestellvolumen beträgt CHF {chf(volume)}.", fill=8),
            page(f"Die Preise werden jährlich um {escalation} % angepasst.", f"Rechnungen sind innert {payment} Tagen zahlbar.", fill=7),
            page(f"Die Haftung der Lieferantin ist auf CHF {chf(cap)} pro Schadenfall begrenzt.", fill=8),
            page(coc_text, fill=8),
            page(f"Jede Partei kann den Vertrag mit einer Frist von {notice} Monaten auf das Ende eines Kalenderjahres kündigen.", fill=8),
            page("Dieser Vertrag untersteht schweizerischem Recht. Gerichtsstand ist St. Gallen.", fill=7),
        ]))

    for idx, name, volume, coc in CUSTOMERS:
        t = CUSTOMER_TERMS[idx]
        say(CON, f"Der Liefervertrag mit der {name} läuft vom {d(t['start'])} bis {d(t['end'])} {cite(idx, 2)}.")
        say(CON, f"Das jährliche Volumen mit der {name} wird auf CHF {mio(volume)} Mio. geschätzt {cite(idx, 3)}.")
        say(CON, f"Die Preise steigen jährlich um {t['escalation']} % {cite(idx, 4)}.")
        say(CON, f"Die Zahlungsfrist beträgt {t['payment']} Tage {cite(idx, 4)}.")
        say(CON, f"Die Haftung ist auf CHF {chf(t['cap'])} je Schadenfall beschränkt {cite(idx, 5)}.")
        if coc:
            say(CON, f"Der Vertrag mit der {name} enthält ein Kündigungsrecht bei Kontrollwechsel {cite(idx, 6)}.")
        else:
            say(CON, f"Der Vertrag mit der {name} enthält keine Change-of-Control-Klausel {cite(idx, 6)}.")
        say(CON, f"Die ordentliche Kündigungsfrist beträgt {t['notice']} Monate {cite(idx, 7)}.")
        say(CON, f"Es gilt Schweizer Recht mit Gerichtsstand St. Gallen {cite(idx, 8)}.")
    top = sum(c[2] for c in CUSTOMERS[:3]) / YEARS[2025] * 100
    say(CON, f"Die drei grössten Kunden stehen für rund {top:.0f} % des Umsatzes {cite('5.1', 3)}.", note="abgeleitet")

    for idx, name, item, volume in SUPPLIERS:
        end = dt.date(rng.choice([2027, 2028, 2029]), 12, 31)
        DOCS.append(Doc(idx, f"Rahmenvertrag {name}", [
            page(f"Rahmenvertrag über {item} zwischen {name} und {NAME} (fiktiv)", fill=7),
            page(f"Der Vertrag ist bis {d(end)} abgeschlossen.", fill=8),
            page(f"Das Mindestabnahmevolumen beträgt CHF {chf(volume)} pro Jahr.", fill=8),
            page("Die Lieferantin gewährleistet die Rückverfolgbarkeit jeder Charge.", fill=8),
            page("Bei Lieferverzug schuldet die Lieferantin eine Konventionalstrafe.", fill=8),
            page("Unterschriften der Parteien", fill=5),
        ]))
        say(CON, f"Mit der {name} besteht ein Rahmenvertrag über {item} bis {d(end)} {cite(idx, 2)}.")
        say(CON, f"Die Mindestabnahme gegenüber der {name} beträgt CHF {chf(volume)} jährlich {cite(idx, 3)}.")
        say(CON, f"Die {name} garantiert die Rückverfolgbarkeit jeder Charge {cite(idx, 4)}.")


# --- Finanzierung, Personal, IP, Versicherung, Rechtsstreit ----------------------

FINZ = "6. Finanzierung"
HR = "7. Personal und Vorsorge"
IP = "8. Immaterialgüter"
INS = "9. Versicherungen"
LIT = "10. Rechtsstreitigkeiten"


def build_rest() -> None:
    DOCS.append(Doc("6.1", "Kreditvertrag Bodensee Kantonalbank", [
        page(f"Kreditvertrag zwischen der Bodensee Kantonalbank (fiktiv) und der {NAME}", fill=7),
        page("Kreditlimite: CHF 8'000'000, davon fester Vorschuss CHF 6'000'000.", fill=7),
        page("Der Zinssatz für den festen Vorschuss beträgt 2.65 % pro Jahr.", "Der feste Vorschuss ist am 30.09.2030 zur Rückzahlung fällig.", fill=7),
        page("Covenant: Die Nettoverschuldung darf das 2.5-fache des EBITDA nicht übersteigen.", fill=8),
        page("Bei einem Kontrollwechsel kann die Bank den Kredit mit sofortiger Wirkung kündigen.", fill=8),
        page("Sicherheiten: Zession der Forderungen aus Lieferungen und Leistungen.", fill=7),
    ]))
    say(FINZ, f"Die Kreditlimite der Bodensee Kantonalbank beträgt CHF 8 Mio. {cite('6.1', 2)}.")
    say(FINZ, f"Davon ist ein fester Vorschuss von CHF 6.0 Mio. beansprucht {cite('6.1', 2)}.")
    say(FINZ, f"Der feste Vorschuss ist zu 2.65 % verzinst {cite('6.1', 3)}.")
    say(FINZ, f"Die Rückzahlung ist am 30. September 2030 fällig {cite('6.1', 3)}.")
    say(FINZ, f"Die Bank kann den Kredit bei einem Kontrollwechsel sofort kündigen {cite('6.1', 5)}.")
    say(FINZ, f"Als Sicherheit sind die Kundenforderungen zediert {cite('6.1', 6)}.")
    say(FINZ, f"Der Covenant Nettoverschuldung zu EBITDA wird per Ende 2025 eingehalten {cite('6.1', 4)}.")

    DOCS.append(Doc("6.2", "Leasingvertrag Spritzgussmaschinen", [
        page("Leasingvertrag über zwei Spritzgussmaschinen (fiktiv)", fill=7),
        page("Die monatliche Leasingrate beträgt CHF 18'400.", "Laufzeit: 60 Monate ab 01.04.2024.", fill=7),
        page("Der Restwert am Ende der Laufzeit beträgt CHF 95'000.", fill=8),
        page("Unterschriften der Parteien", fill=5),
    ]))
    say(FINZ, f"Für zwei Spritzgussmaschinen zahlt die Gesellschaft monatlich CHF 18'400 Leasing {cite('6.2', 2)}.")
    say(FINZ, f"Der Leasingvertrag läuft über 60 Monate ab dem 1. April 2024 {cite('6.2', 2)}.")
    say(FINZ, f"Der Restwert beträgt CHF 95'000 {cite('6.2', 3)}.")

    managers = [("Dr. Martin Keller", "CEO", 340_000, 6), ("Nadia Brunner", "CFO", 265_000, 6),
                ("Reto Signer", "COO", 248_000, 6), ("Elena Rossi", "Leiterin Vertrieb", 212_000, 3)]
    pages = []
    for name, role, salary, notice in managers:
        pages += [page(f"Arbeitsvertrag {name}, Funktion: {role}", fill=7),
                  page(f"Das Bruttojahresgehalt beträgt CHF {chf(salary)}.", fill=8),
                  page(f"Die Kündigungsfrist beträgt {notice} Monate auf das Ende eines Monats.", fill=8)]
    DOCS.append(Doc("7.1", "Arbeitsverträge Geschäftsleitung", pages))
    for i, (name, role, salary, notice) in enumerate(managers):
        say(HR, f"{name} ({role}) erhält ein Bruttojahresgehalt von CHF {chf(salary)} {cite('7.1', 3 * i + 2)}.")
        say(HR, f"Für {name} gilt eine Kündigungsfrist von {notice} Monaten {cite('7.1', 3 * i + 3)}.")
    say(HR, f"Keiner der Arbeitsverträge der Geschäftsleitung sieht Abgangsentschädigungen vor {cite('7.1', 1)}.")
    say(HR, f"Die Gesamtvergütung der Geschäftsleitung beträgt CHF {chf(sum(m[2] for m in managers))} {cite('7.1', 2)}.", note="abgeleitet")

    DOCS.append(Doc("7.2", "Personalreglement", [page(fill=9, title="Personalreglement (fiktiv)") for _ in range(5)] +
                    [page("Die wöchentliche Arbeitszeit beträgt 42 Stunden.", "Es gelten 25 Ferientage pro Jahr.", fill=7)]))
    say(HR, f"Mitarbeitende haben Anspruch auf 25 Ferientage pro Jahr {cite('7.2', 6)}.")
    say(HR, f"Das Personalreglement ist auf dem aktuellen Stand {cite('7.2', 1)}.")

    DOCS.append(Doc("7.3", "Anschlussvertrag Pensionskasse", [
        page("Anschlussvertrag mit der Sammelstiftung Ostschweiz (fiktiv)", fill=7),
        page("Der Deckungsgrad der Vorsorgeeinrichtung per 31.12.2025 beträgt 112.4 %.", fill=8),
        page("Die Arbeitgeberbeiträge betragen 55 % der gesamten Beiträge.", fill=8),
        page(fill=9), page(fill=9),
    ]))
    say(HR, f"Die Sammelstiftung weist per Ende 2025 einen Deckungsgrad von 112.4 % aus {cite('7.3', 2)}.")
    say(HR, f"Die Arbeitgeberin trägt 55 % der Vorsorgebeiträge {cite('7.3', 3)}.")
    say(HR, f"Aus der beruflichen Vorsorge sind keine Sanierungsbeiträge zu erwarten {cite('7.3', 2)}.")

    DOCS.append(Doc("8.1", "Patentliste", [
        page("EP 3 412 877: Gelenkimplantat mit Gleitschicht, erteilt am 14.08.2019, Schutz bis 22.03.2037.",
             "CH 714 220: Verfahren zur Sterilverpackung, Schutz bis 05.11.2035.", fill=5, title="Patentportfolio (fiktiv)"),
        page(fill=8), page(fill=8), page(fill=8),
    ]))
    say(IP, f"Das wichtigste Patent (EP 3 412 877) schützt das Gelenkimplantat bis 22.03.2037 {cite('8.1', 1)}.")
    say(IP, f"Das Verfahrenspatent zur Sterilverpackung läuft bis 5. November 2035 {cite('8.1', 1)}.")
    say(IP, f"Alle Patente stehen im Eigentum der Gesellschaft {cite('8.1', 1)}.")

    DOCS.append(Doc("8.2", "Softwarelizenz ERP", [
        page("Softwarelizenzvertrag ERP zwischen der Ostwind Software GmbH (fiktiv) und der Gesellschaft", fill=7),
        page("Die jährliche Lizenzgebühr beträgt CHF 74'500.", "Der Vertrag läuft bis 31.12.2028.", fill=7),
        page("Die Lizenz ist nicht übertragbar.", fill=8),
        page(fill=8), page(fill=8), page(fill=6),
    ]))
    say(IP, f"Für die ERP-Software zahlt die Gesellschaft jährlich CHF 74'500 {cite('8.2', 2)}.")
    say(IP, f"Der ERP-Lizenzvertrag läuft bis Ende 2028 {cite('8.2', 2)}.")
    say(IP, f"Die ERP-Lizenz ist nicht übertragbar {cite('8.2', 3)}.")

    DOCS.append(Doc("9.1", "Versicherungspolicen", [
        page("Betriebshaftpflicht: Versicherungssumme CHF 10'000'000 pro Ereignis.", fill=7, title="Versicherungsübersicht (fiktiv)"),
        page("Produktehaftpflicht: Versicherungssumme CHF 20'000'000 pro Ereignis, Selbstbehalt CHF 25'000.", fill=7),
        page("Sachversicherung: Gebäude und Inventar, Versicherungssumme CHF 18'500'000.", fill=7),
        page("Betriebsunterbruch: Haftzeit 12 Monate.", fill=8),
        page(fill=8), page(fill=8),
    ]))
    say(INS, f"Die Betriebshaftpflicht deckt CHF 10 Mio. pro Ereignis {cite('9.1', 1)}.")
    say(INS, f"Die Produktehaftpflicht ist mit CHF 20 Mio. pro Ereignis versichert {cite('9.1', 2)}.")
    say(INS, f"Der Selbstbehalt in der Produktehaftpflicht beträgt CHF 25'000 {cite('9.1', 2)}.")
    say(INS, f"Die Sachversicherung deckt Gebäude und Inventar mit CHF 18.5 Mio. {cite('9.1', 3)}.")
    say(INS, f"Die Betriebsunterbrechungsversicherung hat eine Haftzeit von 12 Monaten {cite('9.1', 4)}.")
    say(INS, f"Der Versicherungsschutz erscheint angemessen {cite('9.1', 1)}.")

    DOCS.append(Doc("10.1", "Klage Nordlicht Medical GmbH", [
        page("Klage der Nordlicht Medical GmbH (fiktiv) gegen die Gesellschaft vor dem Handelsgericht St. Gallen", fill=6),
        page("Die Klägerin fordert Schadenersatz von CHF 1'450'000 wegen angeblich mangelhafter Lieferungen.", fill=7),
        page("Die Gesellschaft bestreitet die Forderung vollumfänglich.", fill=8),
        page("Die Rechtsvertreterin schätzt das Prozessrisiko als gering ein.", fill=8),
        page("Die Hauptverhandlung ist auf den 24.11.2026 angesetzt.", fill=7),
    ]))
    say(LIT, f"Die Nordlicht Medical GmbH klagt auf Schadenersatz von CHF 1.45 Mio. {cite('10.1', 2)}.")
    say(LIT, f"Die Gesellschaft bestreitet die Forderung vollständig {cite('10.1', 3)}.")
    say(LIT, f"Die Rechtsvertreterin beurteilt das Prozessrisiko als gering {cite('10.1', 4)}.")
    say(LIT, f"Die Hauptverhandlung findet am 24.11.2026 statt {cite('10.1', 5)}.")
    say(LIT, f"Weitere Rechtsstreitigkeiten sind nicht bekannt {cite('10.1', 1)}.")


# --- Bereinigtes EBITDA und wörtliche Zitate ------------------------------------
# Läuft nach allen anderen Bausteinen, damit der Zufall der übrigen Dokumente gleich bleibt.

QOE = "11. Bereinigtes EBITDA (Quality of Earnings)"
ADDBACKS = [("Beratungskosten für den Verkaufsprozess (M&A-Berater und Rechtsberatung)", 286_500),
            ("Abgangsentschädigung des ehemaligen Leiters Produktion", 145_000),
            ("Rechtskosten im Verfahren mit der Nordlicht Medical GmbH", 98_200)]


def say_after(section: str, text: str, **kw) -> None:
    """Aussage am Ende eines bestehenden Abschnitts einfügen."""
    last = max(i for i, s in enumerate(REPORT) if s.section == section)
    REPORT.insert(last + 1, Statement(section, text, **kw))


def build_quality_of_earnings() -> None:
    DOCS.append(Doc("2.7", "Aufstellung Sondereffekte 2025", [
        page("Erstellt durch die Geschäftsleitung zuhanden der Käuferin.", fill=6,
             title="Aufstellung einmaliger und betriebsfremder Effekte 2025 (fiktiv)"),
    ] + [page(f"{text}: CHF {chf(amount)}", "Belege: Rechnungen und Vereinbarungen liegen bei.", fill=7)
         for text, amount in ADDBACKS]))
    ebitda = IS[2025]["EBITDA"]
    rent = 120_000
    say(QOE, f"Ausgangspunkt ist das ausgewiesene EBITDA 2025 von CHF {chf(ebitda)} {cite('2.3', 4)}.")
    for n, (text, amount) in enumerate(ADDBACKS, start=1):
        say(QOE, f"Bereinigung {n}: {text}, CHF {chf(amount)} {cite('2.7', n + 1)}.")
    say(QOE, f"Bereinigung 4: Marktübliche Miete statt der tieferen Miete an den Hauptaktionär, CHF {chf(rent)}.")
    REPORT[-1].correct, REPORT[-1].error = False, "Bereinigung ohne Beleg"
    total = ebitda + sum(a for _, a in ADDBACKS) + rent
    # Die Summe stimmt; weil Bereinigung 4 keinen Beleg hat, darf sie trotzdem nicht "Geprüft" sein.
    say(QOE, f"Das bereinigte EBITDA 2025 beträgt damit CHF {mio(total)} Mio.", note="folgt aus Bereinigung ohne Beleg")

    say_after(FIN, "Die Revisionsstelle hält fest: „Wir sind auf keine Sachverhalte gestossen, aus denen wir schliessen "
                   f"müssten, dass die Jahresrechnung nicht Gesetz und Statuten entspricht“ {cite('2.4', 2)}.")
    say_after(LIT, f"Die Rechtsvertreterin schreibt: „Das Prozessrisiko ist vernachlässigbar, eine Zahlung ist "
                   f"ausgeschlossen“ {cite('10.1', 4)}.", correct=False, error="Zitat erfunden")


# --- Schweizer Prüfungen: Zeichnungsberechtigung, Bilanzzeilen, gesetzliche Sätze -----
# Läuft ohne Zufall, damit die übrigen Dokumente gleich bleiben.

WARNINGS = []


def doc_by_index(index: str) -> Doc:
    return next(d for d in DOCS if d.index == index)


def build_swiss() -> None:
    doc_by_index("1.1").pages[1] += [
        "Zeichnungsberechtigte Personen:",
        "Rohner, Dr. Beatrice, von Altstätten, in St. Gallen, Präsidentin des Verwaltungsrates, mit Einzelunterschrift",
        "Fässler, Luca, von Appenzell, in Oberriet, Mitglied des Verwaltungsrates, ohne Zeichnungsberechtigung",
        "Keller, Dr. Martin, deutscher Staatsangehöriger, in Widnau, Vorsitzender der Geschäftsleitung, mit Kollektivunterschrift zu zweien",
        "Brunner, Nadia, von Balgach, in Heerbrugg, Mitglied der Geschäftsleitung, mit Kollektivunterschrift zu zweien",
        "Signer, Reto, von Altstätten, in Altstätten, mit Kollektivprokura zu zweien",
    ]
    both = f"Für die {NAME}: Dr. Martin Keller, CEO; Nadia Brunner, CFO"
    signed = {idx: both for idx, *_ in CUSTOMERS + SUPPLIERS + LEASES}
    signed["5.1"] = f"Für die {NAME}: Dr. Beatrice Rohner, Präsidentin des Verwaltungsrates"
    signed["4.1.3"] = f"Für die {NAME}: Reto Signer, COO; Nadia Brunner, CFO"
    # Zwei Unterschriften, die die Gesellschaft nicht binden:
    signed["6.1"] = f"Für die {NAME}: Nadia Brunner, CFO"
    signed["6.2"] = f"Für die {NAME}: Thomas Brunner, Leiter Produktion"
    WARNINGS.extend([{"art": "Nachgerechnet", "dokument": "2.3"},  # Vorjahresspalte Personalaufwand, siehe oben
                     {"art": "Zeichnungsberechtigung", "dokument": "6.1"},
                     {"art": "Zeichnungsberechtigung", "dokument": "6.2"}])
    # Ein Nachtrag, der im Datenraum fehlt:
    doc_by_index("4.1.2").pages[-1].append("Die Parteien haben die Mietfläche mit Nachtrag Nr. 1 vom 15.03.2025 "
                                           "um 400 m2 erweitert.")
    WARNINGS.append({"art": "Verweise", "dokument": "4.1.2"})
    for idx, line in signed.items():
        doc_by_index(idx).pages[-1].append(line)
    # Ein Thema aus dem Protokoll, das der Bericht verschweigt:
    doc_by_index("1.4").pages[9].append("Der Verwaltungsrat nimmt Kenntnis von der angekündigten Steuerprüfung der ESTV "
                                        "zur Verrechnungssteuer der Jahre 2022 bis 2024.")
    WARNINGS.append({"art": "Protokolle", "dokument": "1.4"})

    balance = next(p for p in doc_by_index("2.3").pages if p and p[0].startswith("Bilanz per"))
    assets = sum(int(re.sub(r"\D", "", row.rsplit(" ", 1)[1])) for row in balance[1:5])
    balance += ["Aktienkapital 1'200'000", "Gesetzliche Gewinnreserve 240'000", f"Bilanzsumme {chf(assets)}"]

    # Q&A-Liste: Management-Antworten als eigene Quelle, ein Eintrag falsch zitiert
    DOCS.append(Doc("12.1", "Q&A-Liste Projekt Säntis", [], kind="xlsx", sheets=[("Q&A", [
        ["Nr", "Frage", "Antwort", "Datum"],
        [1, "Wie hoch ist der Auftragsbestand per 30.06.2026?", "Der Auftragsbestand beträgt CHF 15'640'000.", "12.08.2026"],
        [2, "Welche Kunden machen mehr als 10 % des Umsatzes aus?",
         "Alpstein Kliniken AG mit 20.1 % und Spitalverbund Ostschweiz mit 15.0 % des Umsatzes 2025.", "12.08.2026"],
        [3, "Gibt es Garantiefälle über CHF 50'000?",
         "Nein. Die Garantierückstellung per 31.12.2025 beträgt CHF 210'000.", "19.08.2026"],
        [4, "Wann läuft die ISO-13485-Zertifizierung ab?", "Das Zertifikat ist gültig bis 14.11.2027.", "19.08.2026"],
        [5, "Gab es seit dem 31.12.2025 Zahlungen an die Aktionärin?",
         "Am 15.03.2026 wurde eine Management Fee von CHF 60'000 an die Rohner Holding AG bezahlt.", "26.08.2026"],
    ])]))
    # Leakage: Zahlung an die Aktionärin nach dem Locked-Box-Stichtag im SPA-Entwurf (spa-entwurf.md)
    WARNINGS.append({"art": "Leakage", "dokument": "12.1"})
    QA = "12. Management-Antworten (Q&A)"
    say(QA, "Der Auftragsbestand per 30.06.2026 beträgt CHF 15.64 Mio. [Q&A 1].")
    say(QA, "Die Alpstein Kliniken AG steht für 20.1 % des Umsatzes 2025 [Q&A 2].")
    say(QA, "Die Garantierückstellung per 31.12.2025 beträgt CHF 210'000 [Q&A 3].")
    say(QA, "Das ISO-13485-Zertifikat ist gültig bis 14.11.2027 [Q&A 2].", correct=False, error="falscher Q&A-Eintrag")

    # Bewertung: Unternehmenswert und Equity Value werden nachgerechnet
    VAL = "13. Bewertung und Kaufpreis"
    say(VAL, "Bewertet mit dem 7.5-fachen bereinigten EBITDA 2025 ergibt sich ein Unternehmenswert von CHF 44.70 Mio.",
        note="folgt aus Bereinigung ohne Beleg")
    say(VAL, "Nach Abzug der Nettoverschuldung per 31.12.2025 beträgt der Equity Value CHF 40.82 Mio.",
        note="folgt aus Bereinigung ohne Beleg")

    # MWST-Abrechnungen im Format der ESTV; deklariert ist weniger als die Nettoerlöse der Jahresrechnung
    declared = YEARS[2025] - 1_240_000
    shares = (24, 25, 26, 25)
    vat = doc_by_index("3.3")
    for q, page_lines in enumerate(vat.pages, 1):
        total = declared * shares[q - 1] // 100 if q < 4 else declared - sum(declared * s // 100 for s in shares[:3])
        export = total * 7 // 100
        taxable = total - export
        tax = round(taxable * 0.081)
        i = next(n for n, line in enumerate(page_lines) if line.startswith(f"Quartal {q}:"))
        page_lines[i:i + 1] = [
            f"Abrechnungsperiode Quartal {q} 2025, effektive Methode",
            f"Ziffer 200 Total der vereinbarten Entgelte: CHF {chf(total)}",
            f"Ziffer 220 Leistungen ins Ausland: CHF {chf(export)}",
            f"Ziffer 302 Leistungen zum Normalsatz 8.1 %: Umsatz CHF {chf(taxable)}, Steuer CHF {chf(tax)}",
            f"Ziffer 405 Vorsteuer auf Material- und Dienstleistungsaufwand: CHF {chf(tax * 6 // 10)}",
        ]
    WARNINGS.append({"art": "MWST", "dokument": "3.3"})

    say_after(TAX, "Seit 2024 beträgt der MWST-Normalsatz 8.1 %.")
    say_after(TAX, "Die Gesellschaft rechnet ihre Umsätze zum MWST-Normalsatz von 7.7 % ab.",
              correct=False, error="veralteter MWST-Satz")
    say_after(TAX, "Auf Dividenden an die Aktionäre fällt die Verrechnungssteuer von 35 % an.")


# --- Fehler einbauen --------------------------------------------------------------

def plant(where: str, new: str, error: str, detectable: bool = True) -> None:
    """Ersetzt in genau einer Aussage einen Teil und markiert sie als falsch."""
    hits = [s for s in REPORT if where in s.text]
    assert len(hits) == 1, (where, len(hits))
    s = hits[0]
    old, repl = new.split(" => ")
    assert old in s.text, (old, s.text)
    s.text = s.text.replace(old, repl, 1)
    s.correct, s.error, s.detectable = False, error, detectable


def plant_errors() -> None:
    plant("Das jährliche Volumen mit der Helvetic Ortho GmbH", "2.96 Mio. => 2.69 Mio.", "Zahlendreher")
    plant("fest bis 31. Dezember 2031", "31. Dezember 2031 => 31. Dezember 2032", "falsches Jahr")
    plant("Das Lager in Heerbrugg kostet", f"{cite('4.1.2', 3)} => {cite('4.1.2', 2)}", "falsche Seite")
    plant("Das jährliche Volumen mit der Lakeside Dental SA", f"{cite('5.4', 3)} => {cite('5.3', 3)}", "falsches Dokument")
    plant("Der feste Vorschuss ist zu", "2.65 % => 2.15 %", "falscher Zinssatz")
    t = CUSTOMER_TERMS["5.2"]
    hits = [s for s in REPORT if f"beträgt {t['notice']} Monate {cite('5.2', 7)}" in s.text]
    assert len(hits) == 1
    other = 12 if t["notice"] != 12 else 6
    hits[0].text = hits[0].text.replace(f"{t['notice']} Monate", f"{other} Monate")
    hits[0].correct, hits[0].error = False, "falsche Kündigungsfrist"
    digits = UID.replace("CHE-", "").replace(".", "")
    swapped = digits[:4] + digits[5] + digits[4] + digits[6:]
    wrong_uid = f"CHE-{swapped[:3]}.{swapped[3:6]}.{swapped[6:]}"
    assert digits[4] != digits[5]
    plant(f"(UID {UID})", f"{UID} => {wrong_uid}", "UID vertippt")
    ebitda = IS[2025]["EBITDA"]
    plant("Das EBITDA 2025 beträgt", f"CHF {mio(ebitda)} Mio. => CHF {chf(round(ebitda / 1000))}", "Einheit TCHF/CHF verwechselt")
    plant("Der Jahresgewinn 2025 beläuft sich",
          f"Der Jahresgewinn 2025 beläuft sich auf CHF {mio(IS[2025]['Jahresgewinn'])} Mio. => Der Jahresgewinn 2025 beläuft sich auf CHF {mio(IS[2025]['Betriebsergebnis (EBIT)'])} Mio.",
          "EBIT als Jahresgewinn ausgewiesen")
    plant("Der Vertrag mit der Spitalverbund Ostschweiz (fiktiv) enthält ein Kündigungsrecht",
          "enthält ein Kündigungsrecht bei Kontrollwechsel => enthält keine Klausel zum Kontrollwechsel",
          "Kontrollwechselklausel übersehen", detectable=False)
    plant("Der Materialaufwand 2025 belief sich",
          f"CHF {mio(IS[2025]['Materialaufwand'])} Mio. => CHF {mio(IS[2024]['Materialaufwand'])} Mio.",
          "Vorjahreswert als aktuelles Jahr")
    plant("Das EBITDA 2024 betrug", f"CHF {mio(IS[2024]['EBITDA'])} Mio. => CHF {mio(IS[2024]['EBITDA'] + 61_000)} Mio.",
          "falsch gerundet")


# --- Ausgabe --------------------------------------------------------------------

class PDF(FPDF):
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", size=8)
        self.cell(0, 10, f"Seite {self.page_no()}", align="C")


def write_pdf(doc: Doc) -> None:
    pdf = PDF(format="A4")
    pdf.set_auto_page_break(False)
    for paragraphs in doc.pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for p in paragraphs:
            pdf.multi_cell(0, 5, p)
            pdf.ln(2)
        assert pdf.get_y() < 280, f"{doc.index}: Seite zu voll"
    pdf.output(str(OUT / f"{doc.index} {doc.title}.pdf"))


def write_xlsx(doc: Doc) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in doc.sheets:
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, int):
                    cell.number_format = "#,##0"
    wb.save(OUT / f"{doc.index} {doc.title}.xlsx")


def write_report() -> None:
    lines = [
        f"# Due Diligence Report: {NAME} (fiktiv)",
        "",
        "Entwurf für das Investment Committee. Alle Firmen, Personen und Zahlen sind erfunden.",
        "",
    ]
    section = None
    for s in REPORT:
        if s.section != section:
            section = s.section
            lines += ["", f"## {section}", ""]
        lines.append(s.text)
    (HERE / "dd-bericht.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    build_corporate()
    build_financials()
    build_tax()
    build_real_estate()
    build_contracts()
    build_rest()
    plant_errors()
    build_quality_of_earnings()
    build_swiss()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        old.unlink()
    for doc in DOCS:
        (write_xlsx if doc.kind == "xlsx" else write_pdf)(doc)
    write_report()
    truth = [
        {"aussage": s.text, "richtig": s.correct, "fehler": s.error,
         "regeln_koennen_es_sehen": s.detectable, "hinweis": s.note}
        for s in REPORT
    ]
    (HERE / "wahrheit.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "widersprueche.json").write_text(json.dumps(CONFLICTS, ensure_ascii=False, indent=1), encoding="utf-8")
    (HERE / "warnsignale.json").write_text(json.dumps(WARNINGS, ensure_ascii=False, indent=1), encoding="utf-8")
    pages = sum(len(d.pages) or len(d.sheets) for d in DOCS)
    print(f"{len(DOCS)} Dokumente, {pages} Seiten, {len(REPORT)} Aussagen, "
          f"{sum(not s.correct for s in REPORT)} Fehler, {len(CONFLICTS)} Widersprüche im Datenraum")


if __name__ == "__main__":
    main()
