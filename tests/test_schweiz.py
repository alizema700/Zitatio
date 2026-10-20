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
