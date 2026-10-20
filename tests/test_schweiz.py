"""Schweizer Prüfungen: Zeichnungsberechtigung, Kapitalschutz, gesetzliche Sätze."""

import datetime as dt

from zitatio.dataroom import DataRoom
from zitatio.pipeline import run_check
from zitatio.report import parse_report
from zitatio.swiss import apply_rates, check_capital, check_signatures, swiss_flags
from zitatio.verify import Status, verify

HR = """Handelsregister des Kantons Zürich - Auszug
Firma: Muster AG
Aktienkapital: CHF 100'000, eingeteilt in 100 Namenaktien zu CHF 1'000, vollständig liberiert.
Huber, Anna, von Zürich, in Zürich, Präsidentin des Verwaltungsrates, mit Einzelunterschrift
Meier, Dr. Paul, von Bern, in Zürich, Geschäftsführer, mit Kollektivunterschrift zu zweien
Frei, Lea, von Basel, in Zürich, mit Kollektivprokura zu zweien
Graf, Urs, von Chur, in Chur, Mitglied des Verwaltungsrates, ohne Zeichnungsberechtigung
"""


def _room(**docs) -> DataRoom:
    room = DataRoom()
    room.add("1.1 Handelsregisterauszug.txt", HR.encode())
    for name, text in docs.items():
        room.add(name, text.encode())
    return room


def _warned(room: DataRoom) -> set[str]:
    return {d for f in check_signatures(room) if f.level == "warnung" for d in f.docs}


def test_signatures_are_checked_against_the_commercial_register():
    room = _room(**{
        "4.1 Mietvertrag.txt": "Mietvertrag\nFür die Muster AG: Anna Huber, Präsidentin",
        "4.2 Liefervertrag.txt": "Liefervertrag\nFür die Muster AG: Dr. Paul Meier, CEO; Lea Frei, Prokuristin",
        "4.3 Kreditvertrag.txt": "Kreditvertrag\nFür die Muster AG: Dr. Paul Meier, CEO",
        "4.4 Leasingvertrag.txt": "Leasingvertrag\nFür die Muster AG: Urs Graf, Verwaltungsrat",
        "4.5 Lizenzvertrag.txt": "Lizenz\nFür die Muster AG: Hans Meier, Einkauf",
        "4.6 NDA.txt": "NDA\nFür die Lieferantin AG: Max Muster",
    })
    assert _warned(room) == {"4.3", "4.4", "4.5"}


def test_capital_loss_and_over_indebtedness():
    balance = "Muster AG - Jahresrechnung 2025\nBilanz per 31.12.2025 (in CHF)\nAktienkapital 100'000\n" \
              "Gesetzliche Gewinnreserve 20'000\nEigenkapital {}\n"
    for equity, expected in (("80'000", "ok"), ("50'000", "warnung"), ("-10'000", "warnung")):
        room = _room(**{"2.1 Jahresrechnung 2025.txt": balance.format(equity)})
        flag, = check_capital(room)
        assert flag.level == expected, equity
    flag, = check_capital(_room(**{"2.1 Jahresrechnung 2025.txt": balance.format("-10'000")}))
    assert "Überschuldung" in flag.title and "725b" in flag.text


def test_statutory_rates_are_checked_against_the_law():
    text = ("Seit 2024 beträgt der MWST-Normalsatz 8.1 %.\n\nDer MWST-Normalsatz beträgt 7.7 %.\n\n"
            "Der MWST-Normalsatz 2022 lag bei 7.7 %.\n\nAuf Dividenden fällt eine Verrechnungssteuer von 35 % an.")
    findings = verify(parse_report(text), DataRoom())
    apply_rates(findings, today=dt.date(2026, 1, 1))
    assert [f.status for f in findings] == [Status.GEPRUEFT, Status.ABWEICHUNG, Status.GEPRUEFT, Status.GEPRUEFT]
    assert "8.1 %" in findings[1].reasons[0] and "MWSTG" in findings[1].reasons[0]


def test_sentence_ending_with_percent_sign_is_split():
    claims = parse_report("Die Marge beträgt 8.1 %. Der Umsatz wuchs um 3 %.")
    assert len(claims) == 2


def test_report_shows_swiss_section():
    room = _room(**{"4.3 Kreditvertrag.txt": "Kreditvertrag\nFür die Muster AG: Dr. Paul Meier, CEO"})
    run = run_check("b.md", "Text.", b"Text.", room)
    assert any(f.level == "warnung" for f in run.flags)
    from zitatio.render import to_html
    assert "Prüfungen im Datenraum" in to_html(run) and swiss_flags(room)


def test_income_statement_is_recomputed():
    from zitatio.consistency import check_income_statements
    pnl = ("Muster AG - Erfolgsrechnung 2025 (in CHF)\n"
           "Nettoerlös 1'000'000\nMaterialaufwand 400'000\nPersonalaufwand 300'000\n"
           "Übriger betrieblicher Aufwand 100'000\nEBITDA {}\n")
    assert check_income_statements(_room(**{"2.1 Erfolgsrechnung.txt": pnl.format("200'000")})) == []
    flag, = check_income_statements(_room(**{"2.1 Erfolgsrechnung.txt": pnl.format("230'000")}))
    assert flag.level == "warnung" and "EBITDA" in flag.title and "30'000" in flag.text


def test_report_contradicting_itself():
    from zitatio.consistency import report_conflicts
    text = ("Das EBITDA 2025 betrug CHF 2.1 Mio.\n\nIm Ausblick steht: Das EBITDA 2025 lag bei CHF 2'100'000.\n\n"
            "Zusammengefasst erreichte das EBITDA 2025 CHF 2.4 Mio.")
    findings = verify(parse_report(text), DataRoom())
    conflict, = report_conflicts(findings)
    assert len(conflict.values) == 2 and "EBITDA 2025" in conflict.title
    assert all(f.status is Status.WIDERSPRUCH for f in findings)
    assert "Aussage 3" in findings[0].reasons[-1] and "Aussage 1" in findings[2].reasons[-1]


def test_minutes_topics_missing_in_report():
    from zitatio.minutes import check_minutes
    room = _room(**{"1.4 Protokolle Verwaltungsrat 2025.txt": (
        "Protokoll\nDer Verwaltungsrat nimmt Kenntnis von der angekündigten Steuerprüfung der ESTV.\n"
        "Der Verwaltungsrat bespricht die Klage der Kunde AG.\n"
        "Die Parteien bemühen sich, Streitigkeiten einvernehmlich beizulegen.")})
    flags = check_minutes(room, "Gegen die Gesellschaft ist eine Klage der Kunde AG hängig.")
    assert [(f.level, f.title.split(" (")[0]) for f in flags] == [("warnung", "Steuerprüfung"), ("hinweis", "Rechtsstreit")]


def test_missing_amendment_is_flagged():
    from zitatio.references import missing_amendments
    room = _room(**{"4.1 Mietvertrag Halle.txt": ("Mietvertrag\nDie Mietfläche wurde mit Nachtrag Nr. 2 vom 01.03.2025 erweitert.\n"
                                                  "Änderungen dieses Vertrags bedürfen der Schriftform.")})
    flag, = missing_amendments(room)
    assert flag.level == "warnung" and "Nachtrag Nr. 2" in flag.title
    room.add("4.1.1 Nachtrag Nr. 2 Mietvertrag Halle.txt", b"Nachtrag")
    assert missing_amendments(room) == []


def test_indirect_partial_liquidation_needs_twenty_percent_private_holders():
    from zitatio.swiss import check_partial_liquidation

    def flags(book: str):
        room = DataRoom()
        room.add("1.3 Aktienbuch.txt", book.encode())
        return check_partial_liquidation(room)

    hit = flags("Aktienbuch\nAnna Muster: 600 Namenaktien (60 %)\nBeta Holding AG: 400 Namenaktien (40 %)\n")
    assert len(hit) == 1 and "60 %" in hit[0].title and "Art. 20a" in hit[0].text
    assert flags("Aktienbuch\nAnna Muster: 100 Namenaktien\nBeta Holding AG: 900 Namenaktien\n") == []


def test_vat_turnover_is_reconciled_with_the_annual_accounts():
    from zitatio.vat import check_vat

    statement = ("Muster AG - Jahresrechnung 2025\nErfolgsrechnung 2025 (in CHF)\nNettoerlöse aus Lieferungen und "
                 "Leistungen 10'000'000\nBilanz per 31.12.2025 (in CHF)\nAktienkapital 100'000\nEigenkapital 900'000\n")

    def quarters(totals, tax_ok=True):
        pages = []
        for q, total in enumerate(totals, 1):
            tax = round(total * 0.081) + (0 if tax_ok or q != 2 else 900)
            pages.append(f"Quartal {q}\nZiffer 200 Total der vereinbarten Entgelte: CHF {total:,}\n"
                         f"Ziffer 302 Leistungen zum Normalsatz 8.1 %: Umsatz CHF {total:,}, Steuer CHF {tax:,}"
                         .replace(",", "'"))
        return "\f".join(pages)

    def flags(totals, **kw):
        room = _room(**{"2.1 Jahresrechnung 2025.txt": statement, "3.1 MWST-Abrechnungen 2025.txt": quarters(totals, **kw)})
        return check_vat(room)

    ok, = flags([2_500_000, 2_500_000, 2_480_000, 2_510_000])
    assert ok.level == "ok"
    gap, = flags([2_400_000, 2_400_000, 2_400_000, 2_400_000])
    assert gap.level == "warnung" and "400'000 weniger deklariert" in gap.title
    assert "32'400" in gap.text and "Art. 42 MWSTG" in gap.text  # 8.1 % Nachsteuer, Verjährung
    missing, = flags([2_500_000, 2_500_000, 2_500_000])
    assert "Nur 3 von 4" in missing.title
    wrong_tax = [f for f in flags([2_500_000] * 4, tax_ok=False) if "Steuer nicht" in f.title]
    assert len(wrong_tax) == 1 and "S. 2" in wrong_tax[0].title


def test_personal_data_in_the_data_room_is_flagged():
    from zitatio.privacy import check_privacy

    room = _room(**{
        "7.1 Arbeitsvertrag.txt": "Arbeitsvertrag Anna Huber\nAHV-Nr. 756.4821.0937.17\nLohn CHF 120'000",
        "7.2 Personal.txt": "Frau Huber ist seit März krankheitsbedingt abwesend; ein Arztzeugnis liegt vor.",
        "7.3 Reglement.txt": "Bei Krankheit ist ab dem dritten Tag ein Arztzeugnis vorzulegen.",  # allgemein
        "7.4 Liste.txt": "Referenz 756.4821.0937.18",  # Prüfziffer falsch: keine AHV-Nummer
    })
    flags = {f.docs[0]: f for f in check_privacy(room)}
    assert set(flags) == {"7.1", "7.2"}
    assert "AHV-Nummer" in flags["7.1"].text and "Art. 5 lit. c DSG" in flags["7.2"].text


def test_taxable_profit_is_reconciled_with_net_income():
    from zitatio.vat import check_taxable_profit

    statement = ("Muster AG - Jahresrechnung 2024\nErfolgsrechnung (in CHF) 2024 2023\nSteuern 200'000 180'000\n"
                 "Jahresgewinn 1'000'000 900'000\n")
    for taxable, level, word in (("1'030'000", "ok", "passt"), ("1'400'000", "hinweis", "Aufrechnungen"),
                                 ("400'000", "hinweis", "unter")):
        room = _room(**{"2.1 Jahresrechnung 2024.txt": statement,
                        "3.1 Veranlagungsverfügung 2024.txt": f"Steuerbarer Reingewinn 2024: CHF {taxable}"})
        flag, = check_taxable_profit(room)
        assert (flag.level, word in flag.title) == (level, True), taxable


def test_documents_listed_in_the_index_but_missing():
    from zitatio.references import check_index

    index = ("Datenraum-Index Projekt Muster\n1 Gesellschaft\n1.1 Handelsregisterauszug\n2 Finanzen\n"
             "2.1 Jahresrechnung 2024\n2.2 Jahresrechnung 2025\n3 Verträge\n3.1 Mietvertrag\n")
    room = _room(**{"0.1 Datenraum-Index.txt": index, "2.1 Jahresrechnung 2024.txt": "Jahresrechnung",
                    "3.1 Mietvertrag.txt": "Mietvertrag"})
    flag, = check_index(room)
    assert flag.title.startswith("1 Dokument im Index") and "2.2 Jahresrechnung 2025" in flag.text
    assert "3 Verträge" not in flag.text  # Kapitel mit vorhandenen Dokumenten
    assert check_index(_room(**{"3.1 Mietvertrag.txt": "Indexmiete nach Landesindex"})) == []


def test_review_regressions():
    from zitatio.kaufvertrag import check_spa
    from zitatio.privacy import check_privacy
    from zitatio.references import check_index
    from zitatio.vat import check_vat
    from zitatio.word import markdown_to_docx

    # Quartale als eigene Dokumente: eine Abstimmung pro Jahr
    statement = ("Muster AG - Jahresrechnung 2025\nErfolgsrechnung 2025 (in CHF)\nNettoerlöse aus Lieferungen und "
                 "Leistungen 10'000'000\nBilanz per 31.12.2025 (in CHF)\nAktienkapital 100'000\nEigenkapital 900'000\n")
    docs = {f"3.{q} MWST-Abrechnung Q{q} 2025.txt": f"Quartal {q}\nZiffer 200 Total: CHF 2'500'000" for q in range(1, 5)}
    flag, = check_vat(_room(**{"2.1 Jahresrechnung 2025.txt": statement}, **docs))
    assert flag.level == "ok"
    # Kapitelüberschrift mit Punkt; "Mietzins-Index" ist kein Datenraum-Index
    index = "Datenraum-Index\n1.2 Verträge\n1.2.1 Mietvertrag\n"
    assert check_index(_room(**{"0.1 Datenraum-Index.txt": index, "1.2.1 Mietvertrag.txt": "Miete"})) == []
    assert check_index(_room(**{"4.9 Mietzins-Index 2024.txt": "2024 Landesindex 107.1"})) == []
    # Allgemeine Police ist keine Gesundheitsangabe zu einer Person
    policy = "Leistungen bei Krankheit: Arbeitnehmer Lohnfortzahlung ab Vorlage Arztzeugnis."
    assert check_privacy(_room(**{"9.1 Krankentaggeld-Police.txt": policy})) == []
    # Käufer vor der Verkäuferin: seine Aktien zählen nicht
    room = _room(**{"1.3 Aktienbuch.txt": "Aktienbuch\nBeat Keller: 600 Namenaktien\nHans Keller: 400 Namenaktien\n"})
    spa = "zwischen Hans Keller, Zürich, als Käufer, und Beat Keller, Bern (Verkäufer). Der Verkäufer verkauft 1'000 Namenaktien."
    assert any("hält 600" in f.title for f in check_spa("spa.md", spa, room))
    # Steuerzeichen aus PDF-Text machen das Word-XML nicht kaputt
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(markdown_to_docx("Text \x08 mit Steuerzeichen\n\n| a | b |\n|---|---|\n| 1 |"))) as z:
        ET.fromstring(z.read("word/document.xml"))


def test_monthly_sheets_add_up_to_the_overview():
    from zitatio.monatswerte import check_monthly_totals

    months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    pages = [f"Blatt: {m} 2025\nUmsatz; 1'000\nEBITDA; 100" for m in months]
    for overview, expected in (("Umsatz kumuliert; 12'000\nEBITDA kumuliert; 1'200", 0),
                               ("Umsatz kumuliert; 12'500\nEBITDA kumuliert; 1'200", 1)):
        room = _room(**{"2.5 Management Accounts 2025.txt": "\f".join(pages + ["Blatt: Übersicht\n" + overview])})
        flags = check_monthly_totals(room)
        assert len(flags) == expected
    assert "Summe der Monate 12'000" in flags[0].title


def test_management_accounts_against_annual_accounts():
    from zitatio.monatswerte import check_management_vs_statutory

    months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    pages = [f"Blatt: {m} 2025\nManagement Accounts, in TCHF\nUmsatz; 1'000\nEBITDA; 80" for m in months]
    statement = ("Muster AG - Jahresrechnung 2025\nErfolgsrechnung 2025 (in CHF)\nNettoerlöse aus Lieferungen und "
                 "Leistungen 12'010'000\nEBITDA 1'200'000\n")
    room = _room(**{"2.1 Jahresrechnung 2025.txt": statement, "2.5 Management Accounts 2025.txt": "\f".join(pages)})
    flags = {f.title.split(" ")[0]: f for f in check_management_vs_statutory(room)}
    assert flags["Umsatz"].level == "ok" and flags["EBITDA"].level == "hinweis" and "-20.0 %" in flags["EBITDA"].text


def test_employment_contracts_against_mandatory_law():
    from zitatio.arbeitsrecht import check_employment

    room = _room(**{
        "7.1 Arbeitsvertrag Huber.txt": "Arbeitsvertrag Anna Huber\nFür die Dauer von fünf Jahren nach Beendigung "
                                        "gilt ein Konkurrenzverbot.\nEs gelten 18 Ferientage pro Jahr.",
        "7.2 Arbeitsvertrag Meier.txt": "Arbeitsvertrag Beat Meier\nDas Konkurrenzverbot gilt 24 Monate.\n"
                                        "Es gelten 25 Ferientage pro Jahr.",
        "7.3 Contrat de travail Dubois.txt": "Contrat de travail\nLa clause de non-concurrence vaut pendant 4 ans.\n"
                                             "Le collaborateur a droit à 4 semaines de vacances.",
        "5.1 Liefervertrag.txt": "Liefervertrag\nKonkurrenzverbot während zehn Jahren.",  # kein Arbeitsvertrag
    })
    flags = sorted((f.docs[0], f.level, f.title.split(" ")[0]) for f in check_employment(room))
    assert flags == [("7.1", "hinweis", "Konkurrenzverbot"), ("7.1", "warnung", "Ferienanspruch"),
                     ("7.3", "hinweis", "Konkurrenzverbot")]


def test_dividends_against_balance_sheet_and_withholding_tax():
    from zitatio.ausschuettung import check_dividends

    statement = ("Muster AG - Jahresrechnung 2024\nBilanz per 31.12.2024 (in CHF)\nAktienkapital 1'000'000\n"
                 "Gesetzliche Gewinnreserve 700'000\nEigenkapital 3'000'000\n")
    cases = (("900'000", set()), ("1'500'000", {"hinweis"}), ("2'000'000", {"warnung"}))
    for amount, levels in cases:
        room = _room(**{"2.1 Jahresrechnung 2024.txt": statement,
                        "1.4 Protokoll Generalversammlung 2025.txt":
                            f"Die Generalversammlung beschliesst eine Dividende von CHF {amount} aus dem Bilanzgewinn 2024."})
        flags = check_dividends(room)
        assert {f.level for f in flags if "Verrechnungssteuer" not in f.title} == levels, amount
        assert any("Verrechnungssteuer" in f.title for f in flags)
    room = _room(**{"2.1 Jahresrechnung 2024.txt": statement,
                    "1.4 Protokoll Generalversammlung 2025.txt": "Die Generalversammlung beschliesst eine Dividende "
                                                                 "von CHF 500'000 für das Geschäftsjahr 2024.",
                    "3.4 Formular 103.txt": "Formular 103: Verrechnungssteuer auf Dividenden CHF 175'000"})
    assert check_dividends(room) == []
