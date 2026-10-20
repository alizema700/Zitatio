"""Prüfungen aus der Recherche: Widersprüche im Datenraum, Vorjahresspalte, falsche Zeile,
wörtliche Zitate, falsches Dokument, abgeleitete Werte, EBITDA-Bereinigungen, Lückenliste."""

import csv
import io

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.render import DISCLOSURE_COLUMNS, to_disclosure_csv, to_html, to_json
from zitatio.verify import Status

JR_2025 = """Muster AG - Jahresrechnung 2025
Erfolgsrechnung 2025 und 2024 (in CHF)
Nettoerlöse aus Lieferungen und Leistungen 20'000'000 18'000'000
Materialaufwand 7'000'000 6'500'000
EBITDA 3'000'000 2'700'000
Betriebsergebnis (EBIT) 2'200'000 2'000'000
Jahresgewinn 1'600'000 1'450'000
"""
JR_2024 = """Muster AG - Jahresrechnung 2024
Erfolgsrechnung 2024 (in CHF)
Nettoerlöse aus Lieferungen und Leistungen 18'000'000
Materialaufwand 6'350'000
"""
REVISION = """Bericht der Revisionsstelle
Wir sind auf keine Sachverhalte gestossen, aus denen wir schliessen müssten, dass die Jahresrechnung nicht dem Gesetz entspricht.
"""
LEASE = "Mietvertrag Lager Muttenz\nDer jährliche Mietzins beträgt CHF 120'000.\n"
SUPPLY = "Liefervertrag mit der Basler Pharma AG\nDas jährliche Volumen beträgt CHF 900'000.\n"
SPECIAL = "Sondereffekte 2025\nBeratungskosten Verkauf: CHF 150'000\nAbfindung: CHF 50'000\n"


def _room(**extra) -> DataRoom:
    room = DataRoom()
    files = {"2.1 Jahresrechnung 2024.txt": JR_2024, "2.2 Jahresrechnung 2025.txt": JR_2025,
             "2.3 Revisionsbericht 2025.txt": REVISION, "2.4 Sondereffekte 2025.txt": SPECIAL,
             "4.1 Mietvertrag Lager Muttenz.txt": LEASE, "5.1 Liefervertrag Basler Pharma AG.txt": SUPPLY}
    files.update(extra)
    for name, text in files.items():
        room.add(name, text.encode())
    return room


def _check(report: str, room: DataRoom | None = None):
    return run_check("bericht.md", report, report.encode(), room or _room())


def test_prior_year_column_is_a_deviation_with_the_right_value():
    f = _check("Der Materialaufwand 2025 betrug CHF 6.5 Mio. [DR 2.2, S. 1].").findings[0]
    assert f.status is Status.ABWEICHUNG
    assert "Spalte 2024" in f.reasons[0] and "CHF 7'000'000" in f.reasons[0]


def test_current_year_column_is_verified():
    f = _check("Der Materialaufwand 2025 betrug CHF 7.0 Mio. [DR 2.2, S. 1].").findings[0]
    assert f.status is Status.GEPRUEFT


def test_value_from_another_row_is_a_deviation():
    f = _check("Der Jahresgewinn 2025 beträgt CHF 2.2 Mio. [DR 2.2, S. 1].").findings[0]
    assert f.status is Status.ABWEICHUNG
    assert "Betriebsergebnis (EBIT)" in f.reasons[0] and "CHF 1'600'000" in f.reasons[0]


def test_two_metrics_in_one_sentence_each_find_their_row():
    f = _check("Der Nettoerlös 2025 beträgt CHF 20 Mio. bei einem EBITDA von CHF 3.0 Mio. [DR 2.2, S. 1].").findings[0]
    assert f.status is Status.GEPRUEFT


def test_contradiction_between_documents_is_reported():
    run = _check("Der Materialaufwand 2024 betrug CHF 6.5 Mio. [DR 2.2, S. 1].")
    assert [c.title for c in run.conflicts] == ["Materialaufwand 2024"]
    f = run.findings[0]
    assert f.status is Status.WIDERSPRUCH
    assert "DR 2.1, S. 1" in f.reasons[-1] and "CHF 6'350'000" in f.reasons[-1]


def test_rounded_values_in_other_documents_are_no_contradiction():
    room = _room(**{"2.5 Management Accounts 2025.txt": "Kennzahlen 2025, in TCHF\nUmsatz; 20'000\nEBITDA; 3'000\n"})
    assert [c.title for c in _check("Text.", room).conflicts] == ["Materialaufwand 2024"]


def test_plan_and_actual_are_not_compared():
    room = _room(**{"2.6 Budget 2025.txt": "Budget 2025, in TCHF\nUmsatz; 21'500\n"})
    assert all("Umsatz" not in c.title for c in _check("Text.", room).conflicts)


def test_verbatim_quote_is_verified_and_invented_quote_is_not():
    run = _check(
        "Die Revisionsstelle schreibt: „Wir sind auf keine Sachverhalte gestossen, aus denen wir schliessen müssten“ "
        "[DR 2.3, S. 1].\n\n"
        "Die Revisionsstelle schreibt: „Die Jahresrechnung ist in jeder Hinsicht fehlerfrei und vollständig“ [DR 2.3, S. 1]."
    )
    ok, invented = run.findings
    assert ok.status is Status.GEPRUEFT
    assert invented.status is Status.ABWEICHUNG
    assert "verändert oder erfunden" in invented.reasons[0]


def test_quote_with_ellipsis_is_verified():
    f = _check("Laut Revisionsstelle sind „keine Sachverhalte gestossen, […] dass die Jahresrechnung nicht dem Gesetz "
               "entspricht“ [DR 2.3, S. 1].").findings[0]
    assert f.status is Status.GEPRUEFT


def test_company_named_in_claim_must_match_cited_document():
    f = _check("Mit der Basler Pharma AG besteht ein Liefervertrag [DR 4.1, S. 1].").findings[0]
    assert f.status is Status.FALSCHE_FUNDSTELLE
    assert "DR 5.1" in f.reasons[0]


def test_document_type_named_in_claim_must_match_cited_document():
    f = _check("Der Mietvertrag ist unbefristet [DR 5.1, S. 1].").findings[0]
    assert f.status is Status.FALSCHE_FUNDSTELLE
    assert "DR 4.1" in f.reasons[0]


def test_growth_and_margin_are_recomputed():
    run = _check(
        "## Finanzen\n\nDer Nettoerlös 2025 beträgt CHF 20 Mio. [DR 2.2, S. 1]. "
        "Das entspricht einem Wachstum von 11.1 % [DR 2.2, S. 1]. "
        "Die EBITDA-Marge 2025 liegt bei 15.0 % [DR 2.2, S. 1]. "
        "Die EBITDA-Marge 2025 liegt bei 17.0 % [DR 2.2, S. 1]."
    )
    _, growth, margin, wrong = run.findings
    assert (growth.status, margin.status) == (Status.GEPRUEFT, Status.GEPRUEFT)
    assert growth.method == "Nachgerechnet" and "11.1 %" in growth.reasons[0]
    assert wrong.status is Status.ABWEICHUNG and "15.0 %" in wrong.reasons[0]


def test_sum_of_earlier_amounts_is_recomputed():
    run = _check(
        "## Kosten\n\nDie Miete beträgt CHF 120'000 [DR 4.1, S. 1]. Das Volumen beträgt CHF 900'000 [DR 5.1, S. 1]. "
        "Insgesamt sind das CHF 1'020'000 [DR 4.1, S. 1]."
    )
    assert run.findings[-1].status is Status.GEPRUEFT


def test_derived_value_that_cannot_be_recomputed_stays_unverified():
    f = _check("Die drei grössten Kunden stehen für rund 40 % des Umsatzes [DR 5.1, S. 1].").findings[0]
    assert f.status is Status.UNGEPRUEFT


ADDBACKS = """## Bereinigtes EBITDA

Das ausgewiesene EBITDA 2025 beträgt CHF 3.0 Mio. [DR 2.2, S. 1].
- Beratungskosten Verkauf: CHF 150'000 [DR 2.4, S. 1].
- Abfindung: CHF 50'000 [DR 2.4, S. 1].
{extra}
Das bereinigte EBITDA 2025 beträgt CHF {total} Mio.
"""


def test_addbacks_that_add_up_and_have_evidence_are_verified():
    run = _check(ADDBACKS.format(extra="", total="3.2"))
    check, = run.addbacks
    assert check.ok and run.findings[-1].status is Status.GEPRUEFT
    assert check.share.quantize(1) == 6


def test_addback_sum_that_does_not_add_up_is_a_deviation():
    run = _check(ADDBACKS.format(extra="", total="3.4"))
    assert not run.addbacks[0].ok
    assert run.findings[-1].status is Status.ABWEICHUNG
    assert "CHF 3'200'000" in run.findings[-1].reasons[0]


def test_addback_without_evidence_blocks_verified_total():
    run = _check(ADDBACKS.format(extra="- Normalisierte Geschäftsführerlöhne: CHF 80'000.", total="3.28"))
    assert run.findings[-2].status is Status.OHNE_BELEG
    assert "Bereinigung ohne Beleg" in run.findings[-2].reasons[0]
    assert run.findings[-1].status is Status.OHNE_BELEG


def test_negative_addback_is_subtracted():
    run = _check(ADDBACKS.format(extra="- abzüglich Auflösung Rückstellung: CHF 100'000 [DR 2.4, S. 1].", total="3.1"))
    assert run.addbacks[0].items[-1][1] < 0


def test_gap_list_names_missing_documents():
    gaps = {g.name: g for g in _check("Text.").gaps}
    assert gaps["Miet- oder Pachtverträge"].present
    assert not gaps["Handelsregisterauszug"].present
    assert gaps["Jahresrechnungen der letzten drei Jahre"].note == "nur 2024, 2025"


def test_disclosure_map_has_one_row_per_evidence_with_document_hash():
    run = _check("Der Materialaufwand 2025 betrug CHF 7.0 Mio. [DR 2.2, S. 1].")
    rows = list(csv.reader(io.StringIO(to_disclosure_csv(run).lstrip("﻿")), delimiter=";"))
    assert rows[0] == DISCLOSURE_COLUMNS
    assert rows[1][3] == "DR 2.2" and len(rows[1][6]) == 64 and rows[1][7] == "1"


def test_report_shows_new_sections():
    run = _check(ADDBACKS.format(extra="", total="3.4"))
    page = to_html(run)
    for heading in ("Widersprüche im Datenraum", "EBITDA-Bereinigungen nachgerechnet", "Erwartete Unterlagen",
                    "Offenlegungskarte"):
        assert heading in page
    assert '"widersprueche"' in to_json(run)


US_CASH_FLOW = """Consolidated Statement of Cash Flows
(In millions, except per share amounts)
2018
2017
Net income
$
5,363
$
4,869
Purchases of property, plant and equipment
(1,577)
(1,373)
"""


def test_us_report_in_millions_is_read_with_its_unit():
    room = DataRoom()
    room.add("1 Annual Report 2018.txt", US_CASH_FLOW.encode())
    text = "Die Investitionen 2018 betragen USD 1'577 Mio. und der Gewinn USD 5.36 Mrd. [DR 1, S. 1]."
    f = run_check("b.md", text, text.encode(), room).findings[0]
    assert f.status is Status.GEPRUEFT


def test_same_number_in_unrelated_document_is_no_wrong_citation():
    room = _room(**{"6.1 Versicherungspolice Gebäude.txt": "Police\nDie Prämie beträgt CHF 7'500'000.\n"})
    f = _check("Der Materialaufwand 2025 betrug CHF 7.5 Mio. [DR 2.2, S. 1].", room).findings[0]
    assert f.status is Status.ABWEICHUNG


def test_averages_are_not_relocated_to_a_random_page():
    room = _room(**{"6.1 Präsentation.txt": "Marktanteil Durchschnitt 12.4 %\n"})
    f = _check("Die durchschnittliche Marge 2024 bis 2025 beträgt 12.4 % [DR 2.2, S. 1].", room).findings[0]
    assert f.status is not Status.FALSCHE_FUNDSTELLE
